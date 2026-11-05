"""
Migration 0021 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0021.py against the dedicated *_test
database: the backfill writes the Python-computed keys for Cyrillic
names, the four columns end NOT NULL, the two nations UNIQUE
constraints and the two PENDING-scoped partial unique indexes exist
next to every pre-existing one, a key collision aborts naming both
displayed names and leaves the database at 0020, and the downgrade
drops the four columns and their constraints.

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

KEY_COLUMNS = {"name_key", "short_name_key"}
NATION_UQ = {"uq_nations_name_key", "uq_nations_short_name_key"}
APP_UQ = {
    "uq_nation_applications_pending_name_key",
    "uq_nation_applications_pending_short_name_key",
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
            return {
                "nation_columns": {
                    c["name"]: c for c in insp.get_columns(NATIONS)
                },
                "nation_uq": {
                    c["name"] for c in insp.get_unique_constraints(NATIONS)
                },
                "app_columns": {c["name"]: c for c in insp.get_columns(APP)},
                "app_indexes": {i["name"] for i in insp.get_indexes(APP)},
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


def _players(url: str) -> None:
    _exec(
        url,
        "INSERT INTO players (id, vk_user_id, created_at) "
        "VALUES ('p1', 42424321, now()), "
        "('p2', 42424322, now()), "
        "('p3', 42424323, now())",
    )


def _nation(url: str, nid: str, pid: str, name: str, short: str, color: str) -> None:
    _exec(
        url,
        "INSERT INTO nations (id, owner_player_id, name, short_name, "
        "color_hex, created_at, created_turn) VALUES "
        f"('{nid}', '{pid}', '{name}', '{short}', '{color}', now(), 3)",
    )


def _application(
    url: str, aid: str, pid: str, status: str, name: str, short: str, color: str
) -> None:
    _exec(
        url,
        "INSERT INTO nation_applications (id, owner_player_id, status, "
        "name, short_name, color_hex, created_at, updated_at) VALUES "
        f"('{aid}', '{pid}', '{status}', '{name}', '{short}', '{color}', "
        "now(), now())",
    )


def test_0021_backfills_cyrillic_keys_and_keeps_schema_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)
    _players(wiped_pg)
    _nation(wiped_pg, "n1", "p1", "Берёза", "БЕРЁЗА", "#0C7CF4")
    # A PENDING application and a DRAFT whose keys would collide —
    # legal: the reserve indexes cover PENDING rows only.
    _application(wiped_pg, "a1", "p2", "PENDING", "Рим", "РИМ", "#6A3446")
    _application(wiped_pg, "a2", "p3", "DRAFT", "рим", "Рим", "#058D1D")

    _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text("SELECT id, name_key || '|' || short_name_key "
                            "FROM nations")
                ).all()
            )
            app_rows = dict(
                conn.execute(
                    sa.text("SELECT id, name_key || '|' || short_name_key "
                            "FROM nation_applications")
                ).all()
            )
    finally:
        engine.dispose()
    assert rows == {"n1": "береза|береза"}
    assert app_rows == {"a1": "рим|рим", "a2": "рим|рим"}

    schema = _schema(wiped_pg)
    for column in KEY_COLUMNS:
        assert schema["nation_columns"][column]["nullable"] is False
        assert schema["app_columns"][column]["nullable"] is False
    assert NATION_UQ <= schema["nation_uq"]
    assert APP_UQ <= schema["app_indexes"]
    assert {"uq_nations_name", "uq_nations_short_name"} <= schema["nation_uq"]
    assert {
        "uq_nation_applications_pending_name",
        "uq_nation_applications_pending_short_name",
    } <= schema["app_indexes"]


def test_0021_collision_aborts_naming_both_names_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0020", monkeypatch)
    _players(wiped_pg)
    # PostgreSQL default collation is also case-sensitive: «Рим» next
    # to «РИМ» is legal at 0020 — the key check must refuse, naming both.
    _nation(wiped_pg, "n1", "p1", "Рим", "Alpha", "#0C7CF4")
    _nation(wiped_pg, "n2", "p2", "РИМ", "Beta", "#6A3446")

    with pytest.raises(RuntimeError) as exc_info:
        _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)

    message = str(exc_info.value)
    assert "Рим" in message
    assert "РИМ" in message
    assert "nations.name_key" in message

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()
    assert version == "0020"
    assert not (set(_schema(wiped_pg)["nation_columns"]) & KEY_COLUMNS)


def test_0021_downgrade_restores_0020_shape_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)
    schema = _schema(wiped_pg)
    assert KEY_COLUMNS <= set(schema["nation_columns"])
    assert KEY_COLUMNS <= set(schema["app_columns"])

    _alembic(wiped_pg, command.downgrade, "0020", monkeypatch)

    schema = _schema(wiped_pg)
    assert not (set(schema["nation_columns"]) & KEY_COLUMNS)
    assert not (set(schema["app_columns"]) & KEY_COLUMNS)
    assert not (schema["nation_uq"] & NATION_UQ)
    assert not (schema["app_indexes"] & APP_UQ)
    assert {"uq_nations_name", "uq_nations_short_name"} <= schema["nation_uq"]
    assert {
        "uq_nation_applications_pending_name",
        "uq_nation_applications_pending_short_name",
    } <= schema["app_indexes"]

    _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)
    schema = _schema(wiped_pg)
    assert KEY_COLUMNS <= set(schema["nation_columns"])
    assert APP_UQ <= schema["app_indexes"]
