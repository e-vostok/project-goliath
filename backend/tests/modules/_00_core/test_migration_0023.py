"""
Migration 0023 tests on a real SQLite file database (0.14.0 unit 6a).

Upgrading 0022 -> 0023 creates ``judge_rating_log``: the journal of
every ``players.judge_rating`` change with its named reason CHECK, the
``source_key`` idempotency UNIQUE, the CASCADE/SET NULL foreign keys
and the (player_id, id) index. Downgrade drops the table.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

TABLE = "judge_rating_log"

COLUMNS = {
    "id",
    "player_id",
    "delta",
    "applied_delta",
    "rating_before",
    "rating_after",
    "reason_code",
    "note",
    "actor_player_id",
    "source_key",
    "created_at",
}
NOT_NULL = {
    "id",
    "player_id",
    "delta",
    "applied_delta",
    "rating_before",
    "rating_after",
    "reason_code",
    "source_key",
    "created_at",
}
NULLABLE = {"note", "actor_player_id"}


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _schema(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            if TABLE not in insp.get_table_names():
                return {}
            return {
                "columns": {c["name"]: c for c in insp.get_columns(TABLE)},
                "checks": {
                    c["name"]: c["sqltext"] for c in insp.get_check_constraints(TABLE)
                },
                "uniques": {
                    u["name"]: u["column_names"]
                    for u in insp.get_unique_constraints(TABLE)
                },
                "fks": {fk["name"]: fk for fk in insp.get_foreign_keys(TABLE)},
                "indexes": {
                    i["name"]: i["column_names"] for i in insp.get_indexes(TABLE)
                },
            }
    finally:
        engine.dispose()


def test_0023_creates_the_journal_table(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0022", monkeypatch)
    assert _schema(url) == {}

    _alembic(url, command.upgrade, "0023", monkeypatch)

    schema = _schema(url)
    assert set(schema["columns"]) == COLUMNS
    for name in NOT_NULL:
        assert schema["columns"][name]["nullable"] is False, name
    for name in NULLABLE:
        assert schema["columns"][name]["nullable"] is True, name

    check = schema["checks"]["ck_judge_rating_log_reason_code"]
    compact = check.replace(" ", "")
    for code in (
        "ORDER_REFUSED",
        "ORDER_REFUSED_LATE",
        "ORDER_OVERDUE",
        "MANUAL",
    ):
        assert f"'{code}'" in check
    assert "reason_codeIN" in compact

    assert schema["uniques"]["uq_judge_rating_log_source_key"] == ["source_key"]

    player_fk = schema["fks"]["fk_judge_rating_log_player_id"]
    assert player_fk["referred_table"] == "players"
    assert player_fk["referred_columns"] == ["id"]
    assert player_fk["constrained_columns"] == ["player_id"]
    actor_fk = schema["fks"]["fk_judge_rating_log_actor_player_id"]
    assert actor_fk["referred_table"] == "players"
    assert actor_fk["constrained_columns"] == ["actor_player_id"]

    assert schema["indexes"]["ix_judge_rating_log_player_id"] == [
        "player_id",
        "id",
    ]


def test_0023_check_and_unique_bite(tmp_path, monkeypatch):
    """The named CHECK and the source_key UNIQUE reject bad rows."""
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0023", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424323, '2026-11-01 00:00:00')"
                )
            )
            with pytest.raises(sa.exc.IntegrityError):
                conn.execute(
                    sa.text(
                        "INSERT INTO judge_rating_log (player_id, delta, "
                        "applied_delta, rating_before, rating_after, "
                        "reason_code, source_key) VALUES "
                        "('p1', -2, -2, 0, -2, 'BOGUS', 'k1')"
                    )
                )
        with engine.begin() as conn:
            row = (
                "INSERT INTO judge_rating_log (player_id, delta, "
                "applied_delta, rating_before, rating_after, reason_code, "
                "source_key) VALUES "
                "('p1', -2, -2, 0, -2, 'ORDER_REFUSED', '{key}')"
            )
            conn.execute(sa.text(row.format(key="k1")))
            with pytest.raises(sa.exc.IntegrityError):
                conn.execute(sa.text(row.format(key="k1")))
    finally:
        engine.dispose()


def test_0023_downgrade_drops_the_table(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0023", monkeypatch)
    assert _schema(url) != {}

    _alembic(url, command.downgrade, "0022", monkeypatch)
    assert _schema(url) == {}

    # A second upgrade recreates the same shape.
    _alembic(url, command.upgrade, "0023", monkeypatch)
    schema = _schema(url)
    assert set(schema["columns"]) == COLUMNS
