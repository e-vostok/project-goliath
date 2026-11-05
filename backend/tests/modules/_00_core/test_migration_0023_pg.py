"""
Migration 0023 tests on real PostgreSQL (module 00_core, 0.14.0 unit 6a).

Same contract as test_migration_0023.py against the dedicated *_test
database, plus the FK behaviour SQLite cannot enforce: deleting the
rated player cascades the journal rows away while deleting the actor
player only nulls ``actor_player_id``. Downgrade drops the table.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from tests.fixtures.postgres import (
    _reset_public_schema,
    _sync_url,
    pg_url,  # noqa: F401
)

pytestmark = pytest.mark.postgres

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


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _schema(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            if TABLE not in insp.get_table_names():
                return {}
            return {
                "columns": {c["name"]: c for c in insp.get_columns(TABLE)},
                "checks": {
                    c["name"]: c["sqltext"]
                    for c in insp.get_check_constraints(TABLE)
                },
                "uniques": {
                    u["name"]: u["column_names"]
                    for u in insp.get_unique_constraints(TABLE)
                },
                "fks": {fk["name"]: fk for fk in insp.get_foreign_keys(TABLE)},
                "indexes": {
                    i["name"]: i["column_names"]
                    for i in insp.get_indexes(TABLE)
                },
            }
    finally:
        engine.dispose()


def _exec(url: str, *statements: str) -> None:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _count(url: str, sql: str) -> int:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(sql)).scalar_one()
    finally:
        engine.dispose()


def _log_row(player: str, actor: str | None, key: str) -> str:
    actor_sql = "NULL" if actor is None else f"'{actor}'"
    return (
        "INSERT INTO judge_rating_log (player_id, delta, applied_delta, "
        "rating_before, rating_after, reason_code, note, actor_player_id, "
        "source_key) VALUES "
        f"('{player}', -2, -2, 0, -2, 'MANUAL', 'test', {actor_sql}, "
        f"'{key}')"
    )


def test_0023_creates_the_journal_table_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0022", monkeypatch)
    assert _schema(wiped_pg) == {}

    _alembic(wiped_pg, command.upgrade, "0023", monkeypatch)

    schema = _schema(wiped_pg)
    assert set(schema["columns"]) == COLUMNS
    for name in COLUMNS - {"note", "actor_player_id"}:
        assert schema["columns"][name]["nullable"] is False, name
    assert schema["columns"]["note"]["nullable"] is True
    assert schema["columns"]["actor_player_id"]["nullable"] is True

    check = schema["checks"]["ck_judge_rating_log_reason_code"]
    for code in (
        "ORDER_REFUSED",
        "ORDER_REFUSED_LATE",
        "ORDER_OVERDUE",
        "MANUAL",
    ):
        assert code in check

    assert schema["uniques"]["uq_judge_rating_log_source_key"] == ["source_key"]

    player_fk = schema["fks"]["fk_judge_rating_log_player_id"]
    assert player_fk["options"]["ondelete"].upper() == "CASCADE"
    actor_fk = schema["fks"]["fk_judge_rating_log_actor_player_id"]
    assert actor_fk["options"]["ondelete"].upper() == "SET NULL"

    assert schema["indexes"]["ix_judge_rating_log_player_id"] == [
        "player_id",
        "id",
    ]


def test_0023_fk_actions_fire_pg(wiped_pg, monkeypatch):
    """Player deletion cascades the journal; actor deletion nulls it."""
    _alembic(wiped_pg, command.upgrade, "0023", monkeypatch)
    _exec(
        wiped_pg,
        "INSERT INTO players (id, vk_user_id, created_at) VALUES "
        "('p1', 42424324, now()), ('a1', 42424325, now()), "
        "('p2', 42424326, now())",
        _log_row("p1", "a1", "k-p1"),
        _log_row("p2", "a1", "k-p2"),
    )

    # Deleting the rated player removes its journal rows.
    _exec(wiped_pg, "DELETE FROM players WHERE id = 'p1'")
    assert _count(wiped_pg, "SELECT count(*) FROM judge_rating_log") == 1
    assert _count(
        wiped_pg,
        "SELECT count(*) FROM judge_rating_log WHERE player_id = 'p2'",
    ) == 1

    # Deleting the actor keeps the row and nulls the reference.
    _exec(wiped_pg, "DELETE FROM players WHERE id = 'a1'")
    assert _count(
        wiped_pg,
        "SELECT count(*) FROM judge_rating_log WHERE player_id = 'p2' "
        "AND actor_player_id IS NULL",
    ) == 1


def test_0023_downgrade_drops_the_table_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0023", monkeypatch)
    assert _schema(wiped_pg) != {}

    _alembic(wiped_pg, command.downgrade, "0022", monkeypatch)
    assert _schema(wiped_pg) == {}

    _alembic(wiped_pg, command.upgrade, "0023", monkeypatch)
    assert set(_schema(wiped_pg)["columns"]) == COLUMNS
