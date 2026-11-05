"""
Migration 0021 tests on a real SQLite file database (0.14.0 unit 3b).

Upgrading 0020 -> 0021 adds ``name_key``/``short_name_key`` to
``nations`` and ``nation_applications``, backfills them in Python
(casefold + «ё»→«е», so a Cyrillic name proves the Python path), pins
NOT NULL, and adds two UNIQUE constraints on nations plus two
PENDING-scoped partial unique indexes on applications — while every
pre-existing constraint and index stays. A key collision aborts the
upgrade naming both displayed names and leaves the database at 0020.
Downgrade drops the four columns and their constraints.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

APP = "nation_applications"
NATIONS = "nations"

KEY_COLUMNS = {"name_key", "short_name_key"}
NATION_UQ = {"uq_nations_name_key", "uq_nations_short_name_key"}
APP_UQ = {
    "uq_nation_applications_pending_name_key",
    "uq_nation_applications_pending_short_name_key",
}


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _unique_on(schema: dict, column: str) -> bool:
    """A UNIQUE constraint on exactly ``column`` survives — the
    auto-generated constraint name differs between SQLite (uq_*) and
    PostgreSQL (<table>_<column>_key), so compare the column set."""
    return [column] in schema["nation_uq"].values()


def _schema(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {
                "nation_columns": {
                    c["name"]: c for c in insp.get_columns(NATIONS)
                },
                "nation_uq": {
                    c["name"]: c["column_names"]
                    for c in insp.get_unique_constraints(NATIONS)
                },
                "app_columns": {c["name"]: c for c in insp.get_columns(APP)},
                "app_indexes": {i["name"] for i in insp.get_indexes(APP)},
            }
    finally:
        engine.dispose()


def _exec(url: str, *statements: str) -> None:
    engine = sa.create_engine(url)
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
        "VALUES ('p1', 42424321, '2026-10-01 00:00:00'), "
        "('p2', 42424322, '2026-10-01 00:00:00'), "
        "('p3', 42424323, '2026-10-01 00:00:00')",
    )


def _nation(url: str, nid: str, pid: str, name: str, short: str, color: str) -> None:
    _exec(
        url,
        "INSERT INTO nations (id, owner_player_id, name, short_name, "
        "color_hex, created_at, created_turn) VALUES "
        f"('{nid}', '{pid}', '{name}', '{short}', '{color}', "
        "'2026-10-01 00:00:00', 3)",
    )


def _application(
    url: str, aid: str, pid: str, status: str, name: str, short: str, color: str
) -> None:
    _exec(
        url,
        "INSERT INTO nation_applications (id, owner_player_id, status, "
        "name, short_name, color_hex, created_at, updated_at) VALUES "
        f"('{aid}', '{pid}', '{status}', '{name}', '{short}', '{color}', "
        "'2026-10-01 00:00:00', '2026-10-01 00:00:00')",
    )


def test_0021_backfills_cyrillic_keys_and_keeps_schema(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0020", monkeypatch)
    _players(url)
    _nation(url, "n1", "p1", "Берёза", "БЕРЁЗА", "#0C7CF4")
    # A PENDING application and a DRAFT whose keys would collide —
    # legal: the reserve indexes cover PENDING rows only.
    _application(url, "a1", "p2", "PENDING", "Рим", "РИМ", "#6A3446")
    _application(url, "a2", "p3", "DRAFT", "рим", "Рим", "#058D1D")

    _alembic(url, command.upgrade, "0021", monkeypatch)

    engine = sa.create_engine(url)
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

    schema = _schema(url)
    for column in KEY_COLUMNS:
        assert schema["nation_columns"][column]["nullable"] is False
        assert schema["app_columns"][column]["nullable"] is False
    assert NATION_UQ <= set(schema["nation_uq"])
    assert APP_UQ <= schema["app_indexes"]
    # Every pre-existing uniqueness artefact stays.
    assert _unique_on(schema, "name")
    assert _unique_on(schema, "short_name")
    assert {
        "uq_nation_applications_pending_name",
        "uq_nation_applications_pending_short_name",
    } <= schema["app_indexes"]


def test_0021_collision_aborts_naming_both_names(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0020", monkeypatch)
    _players(url)
    # Exact-match UNIQUE allows «Рим» next to «РИМ» at 0020 — the key
    # computation must refuse the upgrade, naming both.
    _nation(url, "n1", "p1", "Рим", "Alpha", "#0C7CF4")
    _nation(url, "n2", "p2", "РИМ", "Beta", "#6A3446")

    with pytest.raises(RuntimeError) as exc_info:
        _alembic(url, command.upgrade, "0021", monkeypatch)

    message = str(exc_info.value)
    assert "Рим" in message
    assert "РИМ" in message
    assert "nations.name_key" in message

    # The abort happens before any schema change: still 0020, no keys.
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()
    assert version == "0020"
    assert not (set(_schema(url)["nation_columns"]) & KEY_COLUMNS)


def test_0021_downgrade_restores_0020_shape(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0021", monkeypatch)
    schema = _schema(url)
    assert KEY_COLUMNS <= set(schema["nation_columns"])
    assert KEY_COLUMNS <= set(schema["app_columns"])

    _alembic(url, command.downgrade, "0020", monkeypatch)

    schema = _schema(url)
    assert not (set(schema["nation_columns"]) & KEY_COLUMNS)
    assert not (set(schema["app_columns"]) & KEY_COLUMNS)
    assert not (set(schema["nation_uq"]) & NATION_UQ)
    assert not (schema["app_indexes"] & APP_UQ)
    # The pre-existing artefacts survive the round trip.
    assert _unique_on(schema, "name")
    assert _unique_on(schema, "short_name")
    assert {
        "uq_nation_applications_pending_name",
        "uq_nation_applications_pending_short_name",
    } <= schema["app_indexes"]

    # A second upgrade re-adds everything cleanly.
    _alembic(url, command.upgrade, "0021", monkeypatch)
    schema = _schema(url)
    assert KEY_COLUMNS <= set(schema["nation_columns"])
    assert APP_UQ <= schema["app_indexes"]
