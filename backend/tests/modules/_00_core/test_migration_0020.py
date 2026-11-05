"""
Migration 0020 tests on a real SQLite file database (0.14.0 unit 3a).

Upgrading 0019 -> 0020 drops exactly three dead columns:
``nations.anthem_url`` and ``nation_applications.reviewer_player_id``
(with its named FK) plus ``reviewer_assigned_at`` — a nation row
holding an anthem value upgrades without error. Downgrade re-adds the
three columns nullable with the same named FK.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

APP = "nation_applications"
NATIONS = "nations"

DROPPED_NATION = {"anthem_url"}
DROPPED_APP = {"reviewer_player_id", "reviewer_assigned_at"}
REVIEWER_FK = "fk_nation_applications_reviewer_player_id"


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


def test_0020_drops_exactly_the_three_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0019", monkeypatch)
    before = _schema(url)
    assert DROPPED_NATION <= set(before["nation_columns"])
    assert DROPPED_APP <= set(before["app_columns"])
    assert REVIEWER_FK in before["app_fks"]

    _alembic(url, command.upgrade, "0020", monkeypatch)

    schema = _schema(url)
    assert set(before["nation_columns"]) - set(schema["nation_columns"]) == (
        DROPPED_NATION
    )
    assert set(before["app_columns"]) - set(schema["app_columns"]) == DROPPED_APP
    assert REVIEWER_FK not in schema["app_fks"]


def test_0020_keeps_a_row_with_an_anthem_value(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0019", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424302, '2026-10-01 00:00:00')"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations (id, owner_player_id, name, "
                    "short_name, color_hex, anthem_url, created_at, "
                    "created_turn) VALUES ('n1', 'p1', 'Old Realm', "
                    "'Old Realm', '#0C7CF4', 'https://vk.com/audio-1', "
                    "'2026-10-01 00:00:00', 3)"
                )
            )
    finally:
        engine.dispose()

    _alembic(url, command.upgrade, "0020", monkeypatch)

    engine = sa.create_engine(url)
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


def test_0020_downgrade_restores_0019_shape(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0020", monkeypatch)
    assert not (set(_schema(url)["app_columns"]) & DROPPED_APP)

    _alembic(url, command.downgrade, "0019", monkeypatch)

    schema = _schema(url)
    for name in DROPPED_NATION:
        assert schema["nation_columns"][name]["nullable"] is True
    for name in DROPPED_APP:
        assert schema["app_columns"][name]["nullable"] is True
    assert REVIEWER_FK in schema["app_fks"]

    # A second upgrade drops everything cleanly again.
    _alembic(url, command.upgrade, "0020", monkeypatch)
    schema = _schema(url)
    assert not (set(schema["nation_columns"]) & DROPPED_NATION)
    assert not (set(schema["app_columns"]) & DROPPED_APP)
