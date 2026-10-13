"""
Migration 0007 tests on real SQLite file databases (module 02_bot).

Covers Spec Part 1.1 / Appendix B item B5:
- ``upgrade head`` creates the four bot tables (bot_consents,
  bot_outbox, bot_vk_events, bot_state) with the named CHECKs, the
  ``uq_bot_outbox_dedup`` unique, both readiness indexes, and seeds the
  ``bot_state`` singleton row ``(id=1, last_digest_turn=0)``;
- BIGINT PKs autoincrement on SQLite (the tick_log.id lesson);
- ``downgrade`` to 0006 drops exactly the four bot tables and leaves
  every other table intact; re-upgrade works.

Every test drives ``alembic upgrade/downgrade`` against a real file —
no mocks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[3]

BOT_TABLES = {"bot_consents", "bot_outbox", "bot_vk_events", "bot_state"}


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _cfg() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


def _upgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(_cfg(), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(_cfg(), target)


def _table_names(url: str) -> list[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return sa.inspect(conn).get_table_names()
    finally:
        engine.dispose()


def _insert_player(url: str) -> str:
    """One real players row — the FK target the bot tables need."""
    player_id = str(uuid.uuid4())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id) "
                    "VALUES (:id, 777000002)"
                ),
                {"id": player_id},
            )
    finally:
        engine.dispose()
    return player_id


class TestUpgradeToHead:
    def test_four_tables_and_singleton_row(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        assert BOT_TABLES <= set(_table_names(url))

        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    sa.text(
                        "SELECT id, last_digest_turn FROM bot_state"
                    )
                ).mappings().one()
                consents_checks = {
                    c["name"]
                    for c in sa.inspect(conn).get_check_constraints(
                        "bot_consents"
                    )
                }
        finally:
            engine.dispose()

        assert row == {"id": 1, "last_digest_turn": 0}
        assert "ck_bot_consents_state" in consents_checks

    def test_outbox_constraints_and_indexes(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)

        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                insp = sa.inspect(conn)
                checks = {
                    c["name"]
                    for c in insp.get_check_constraints("bot_outbox")
                }
                uniques = insp.get_unique_constraints("bot_outbox")
                indexes = {
                    i["name"] for i in insp.get_indexes("bot_outbox")
                }
                fks = insp.get_foreign_keys("bot_outbox")
        finally:
            engine.dispose()

        assert {
            "ck_bot_outbox_kind",
            "ck_bot_outbox_priority",
            "ck_bot_outbox_status",
        } <= checks
        dedup = [u for u in uniques if u["name"] == "uq_bot_outbox_dedup"]
        assert len(dedup) == 1
        assert dedup[0]["column_names"] == [
            "player_id",
            "type_key",
            "event_key",
        ]
        assert {
            "ix_bot_outbox_ready",
            "ix_bot_outbox_player_status",
        } <= indexes
        assert len(fks) == 1
        assert fks[0]["referred_table"] == "players"
        assert fks[0]["options"].get("ondelete") == "CASCADE"

    def test_autoincrement_ids_on_sqlite(self, tmp_path, monkeypatch):
        """The tick_log.id lesson: bot_outbox and bot_vk_events must
        assign distinct ids to inserts that carry none."""
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        player_id = _insert_player(url)

        engine = sa.create_engine(url)
        try:
            with engine.begin() as conn:
                now = datetime.now(timezone.utc)
                for key in ("a", "b"):
                    conn.execute(
                        sa.text(
                            "INSERT INTO bot_outbox "
                            "(player_id, kind, type_key, event_key, "
                            " priority, counts_toward_cap, payload, "
                            " created_at, not_before, expires_at, "
                            " next_attempt_at) "
                            "VALUES (:pid, 'NOTIFICATION', 'TICK_DIGEST', "
                            " :key, 'normal', 1, '{}', :ts, :ts, :ts, :ts)"
                        ),
                        {"pid": player_id, "key": key, "ts": now},
                    )
                    conn.execute(
                        sa.text(
                            "INSERT INTO bot_vk_events "
                            "(event_id, event_type, received_at) "
                            "VALUES (:eid, 'message_new', :ts)"
                        ),
                        {"eid": f"evt-{key}", "ts": now},
                    )
                outbox_ids = [
                    r[0]
                    for r in conn.execute(
                        sa.text("SELECT id FROM bot_outbox ORDER BY id")
                    )
                ]
                event_ids = [
                    r[0]
                    for r in conn.execute(
                        sa.text(
                            "SELECT id FROM bot_vk_events ORDER BY id"
                        )
                    )
                ]
        finally:
            engine.dispose()

        assert len(outbox_ids) == 2 and outbox_ids[0] != outbox_ids[1]
        assert len(event_ids) == 2 and event_ids[0] != event_ids[1]


class TestDowngradeRoundTrip:
    def test_downgrade_removes_only_bot_tables(
        self, tmp_path, monkeypatch
    ):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        before = set(_table_names(url)) - {"alembic_version"}

        _downgrade(url, "0006", monkeypatch)

        after = set(_table_names(url)) - {"alembic_version"}
        assert BOT_TABLES.isdisjoint(after)
        assert after == before - BOT_TABLES

    def test_upgrade_after_downgrade_works(self, tmp_path, monkeypatch):
        url = _db_url(tmp_path)
        _upgrade(url, "head", monkeypatch)
        _downgrade(url, "0006", monkeypatch)
        _upgrade(url, "head", monkeypatch)

        assert BOT_TABLES <= set(_table_names(url))
        engine = sa.create_engine(url)
        try:
            with engine.connect() as conn:
                assert conn.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM bot_state WHERE id = 1 "
                        "AND last_digest_turn = 0"
                    )
                ).scalar_one() == 1
        finally:
            engine.dispose()
