"""
Migration 0020 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0020.py against the dedicated *_test
database: upgrading 0019 -> 0020 drops exactly the three dead columns
and the reviewer FK on the real dialect, a nation row holding an
anthem value upgrades without error, and the downgrade re-adds the
columns nullable with the same named FK.

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

APP = "nation_applications"
NATIONS = "nations"

DROPPED_NATION = {"anthem_url"}
DROPPED_APP = {"reviewer_player_id", "reviewer_assigned_at"}
REVIEWER_FK = "fk_nation_applications_reviewer_player_id"


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
            return {
                "nation_columns": {
                    c["name"]: c for c in insp.get_columns(NATIONS)
                },
                "app_columns": {c["name"]: c for c in insp.get_columns(APP)},
                "app_fks": {
                    fk["name"]: fk for fk in insp.get_foreign_keys(APP)
                },
            }
    finally:
        engine.dispose()


def test_0020_drops_exactly_the_three_columns_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0019", monkeypatch)
    before = _schema(wiped_pg)
    assert DROPPED_NATION <= set(before["nation_columns"])
    assert DROPPED_APP <= set(before["app_columns"])
    assert before["app_fks"][REVIEWER_FK]["options"].get("ondelete") == (
        "SET NULL"
    )

    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)

    schema = _schema(wiped_pg)
    assert set(before["nation_columns"]) - set(schema["nation_columns"]) == (
        DROPPED_NATION
    )
    assert set(before["app_columns"]) - set(schema["app_columns"]) == DROPPED_APP
    assert REVIEWER_FK not in schema["app_fks"]


def test_0020_keeps_a_row_with_an_anthem_value_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0019", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424302, now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations (id, owner_player_id, name, "
                    "short_name, color_hex, anthem_url, created_at, "
                    "created_turn) VALUES ('n1', 'p1', 'Old Realm', "
                    "'Old Realm', '#0C7CF4', 'https://vk.com/audio-1', "
                    "now(), 3)"
                )
            )
    finally:
        engine.dispose()

    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    sa.text("SELECT name, short_name FROM nations WHERE id = 'n1'")
                )
                .mappings()
                .one()
            )
    finally:
        engine.dispose()
    assert row["name"] == "Old Realm"
    assert row["short_name"] == "Old Realm"


def test_0020_downgrade_restores_0019_shape_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)
    assert not (set(_schema(wiped_pg)["app_columns"]) & DROPPED_APP)

    _alembic(wiped_pg, command.downgrade, "0019", monkeypatch)

    schema = _schema(wiped_pg)
    for name in DROPPED_NATION:
        assert schema["nation_columns"][name]["nullable"] is True
    for name in DROPPED_APP:
        assert schema["app_columns"][name]["nullable"] is True
    assert schema["app_fks"][REVIEWER_FK]["options"].get("ondelete") == (
        "SET NULL"
    )
    assert schema["app_fks"][REVIEWER_FK]["referred_table"] == "players"

    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)
    schema = _schema(wiped_pg)
    assert not (set(schema["nation_columns"]) & DROPPED_NATION)
    assert not (set(schema["app_columns"]) & DROPPED_APP)
