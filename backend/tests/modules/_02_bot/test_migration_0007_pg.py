"""
Migration 0007 tests on real PostgreSQL (module 02_bot).

Same contract as test_migration_0007.py but against the dedicated
*_test database: real FK enforcement (ON DELETE CASCADE actually
runs), real CHECK constraints, real BIGSERIAL-style autoincrement.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from tests.fixtures.postgres import _reset_public_schema, _sync_url, pg_url

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[3]

BOT_TABLES = {"bot_consents", "bot_outbox", "bot_vk_events", "bot_state"}


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _upgrade(url: str, target: str, monkeypatch) -> None:
    # env.py resolves DATABASE_URL; hand it the psycopg2 sync URL.
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.downgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _connect(url: str):
    return sa.create_engine(_sync_url(url))


def _insert_player(url: str, vk_user_id: int = 777000003) -> str:
    player_id = str(uuid.uuid4())
    engine = _connect(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id) "
                    "VALUES (:id, :vk)"
                ),
                {"id": player_id, "vk": vk_user_id},
            )
    finally:
        engine.dispose()
    return player_id


def test_upgrade_head_creates_bot_tables(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            tables = set(insp.get_table_names())
            row = conn.execute(
                sa.text("SELECT id, last_digest_turn FROM bot_state")
            ).mappings().one()
            checks = {
                c["name"]
                for c in insp.get_check_constraints("bot_outbox")
            }
            uniques = insp.get_unique_constraints("bot_outbox")
            indexes = {
                i["name"] for i in insp.get_indexes("bot_outbox")
            }
    finally:
        engine.dispose()

    assert BOT_TABLES <= tables
    assert row == {"id": 1, "last_digest_turn": 0}
    assert {
        "ck_bot_outbox_kind",
        "ck_bot_outbox_priority",
        "ck_bot_outbox_status",
    } <= checks
    assert any(
        u["name"] == "uq_bot_outbox_dedup" for u in uniques
    )
    assert {
        "ix_bot_outbox_ready",
        "ix_bot_outbox_player_status",
    } <= indexes


def test_player_delete_cascades_on_pg(wiped_pg, monkeypatch):
    """Real ON DELETE CASCADE: removing the player removes the
    consent and the queued rows (Spec 1.1)."""
    _upgrade(wiped_pg, "head", monkeypatch)
    player_id = _insert_player(wiped_pg)

    engine = _connect(wiped_pg)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO bot_consents "
                    "(player_id, state, state_source, "
                    " state_changed_at, created_at) "
                    "VALUES (:pid, 'ALLOWED', 'INIT', now(), now())"
                ),
                {"pid": player_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO bot_outbox "
                    "(player_id, kind, type_key, event_key, priority, "
                    " counts_toward_cap, payload, created_at, "
                    " not_before, expires_at, next_attempt_at) "
                    "VALUES (:pid, 'NOTIFICATION', 'TICK_DIGEST', "
                    " 'cascade-test', 'normal', true, '{}'::json, "
                    " now(), now(), now(), now())"
                ),
                {"pid": player_id},
            )
            conn.execute(
                sa.text("DELETE FROM players WHERE id = :pid"),
                {"pid": player_id},
            )
            consents = conn.execute(
                sa.text("SELECT COUNT(*) FROM bot_consents")
            ).scalar_one()
            outbox = conn.execute(
                sa.text("SELECT COUNT(*) FROM bot_outbox")
            ).scalar_one()
    finally:
        engine.dispose()
    assert consents == 0
    assert outbox == 0


def test_constraints_enforced_on_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)
    player_id = _insert_player(wiped_pg)

    engine = _connect(wiped_pg)
    try:
        # Bad consent state → ck_bot_consents_state.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO bot_consents "
                        "(player_id, state, state_source, "
                        " state_changed_at, created_at) "
                        "VALUES (:pid, 'BOGUS', 'INIT', now(), now())"
                    ),
                    {"pid": player_id},
                )
        # Duplicate (player_id, type_key, event_key) → uq_bot_outbox_dedup.
        def _outbox_row(conn):
            conn.execute(
                sa.text(
                    "INSERT INTO bot_outbox "
                    "(player_id, kind, type_key, event_key, priority, "
                    " counts_toward_cap, payload, created_at, "
                    " not_before, expires_at, next_attempt_at) "
                    "VALUES (:pid, 'NOTIFICATION', 'TICK_DIGEST', "
                    " 'dup-key', 'normal', true, '{}'::json, "
                    " now(), now(), now(), now())"
                ),
                {"pid": player_id},
            )

        with engine.begin() as conn:
            _outbox_row(conn)
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _outbox_row(conn)
        # bot_state second row → ck_bot_state_singleton.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO bot_state (id, last_digest_turn) "
                        "VALUES (2, 0)"
                    )
                )
        # Autoincrement on PG: two inserts without id → distinct ids.
        with engine.begin() as conn:
            for eid in ("pg-a", "pg-b"):
                conn.execute(
                    sa.text(
                        "INSERT INTO bot_vk_events "
                        "(event_id, event_type, received_at) "
                        "VALUES (:eid, 'message_new', now())"
                    ),
                    {"eid": eid},
                )
            ids = [
                r[0]
                for r in conn.execute(
                    sa.text("SELECT id FROM bot_vk_events ORDER BY id")
                )
            ]
    finally:
        engine.dispose()
    assert len(ids) == 2 and ids[0] != ids[1]


def test_downgrade_then_upgrade_roundtrip(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)
    _downgrade(wiped_pg, "0006", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            tables = set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()
    assert BOT_TABLES.isdisjoint(tables)
    assert {"players", "nations", "provinces"} <= tables

    _upgrade(wiped_pg, "head", monkeypatch)
    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            assert BOT_TABLES <= set(
                sa.inspect(conn).get_table_names()
            )
            assert conn.execute(
                sa.text("SELECT COUNT(*) FROM bot_state WHERE id = 1")
            ).scalar_one() == 1
    finally:
        engine.dispose()
