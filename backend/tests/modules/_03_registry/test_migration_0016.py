"""
Migration 0016 tests on a real SQLite file database (0.11.0 unit 11 —
permanent Registry numbers for existing players).

A database standing at revision 0015 is seeded with three players; the
upgrade must assign numbers equal to each player's current position in
the (created_at, id) order — the order list_for_registry uses — so no
existing «Игрок №N» or #registry/player-<N> link changes meaning. The
counter lands on the player count (0 on an empty database), the
downgrade drops both tables and a second upgrade re-creates them.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _seed_players(url: str) -> list[str]:
    """Three players with controlled created_at ordering; returns ids
    in (created_at, id) order — the numbering order."""
    ids = [str(uuid.uuid4()) for _ in range(3)]
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for i, pid in enumerate(ids):
                conn.execute(
                    sa.text(
                        "INSERT INTO players (id, vk_user_id, created_at) "
                        "VALUES (:id, :vk, :created)"
                    ),
                    {
                        "id": pid,
                        "vk": 550001 + i,
                        "created": f"2026-09-0{i + 1} 12:00:00",
                    },
                )
    finally:
        engine.dispose()
    return ids


def _numbers(url: str) -> dict[str, int]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return dict(
                conn.execute(
                    sa.text("SELECT player_id, number FROM registry_player_numbers")
                ).all()
            )
    finally:
        engine.dispose()


def _counter(url: str) -> int:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT last_number FROM registry_number_counter WHERE id = 1")
            ).scalar_one()
    finally:
        engine.dispose()


def test_0016_backfills_positions_as_permanent_numbers(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0015", monkeypatch)
    ids = _seed_players(url)

    _alembic(url, command.upgrade, "0016", monkeypatch)

    numbers = _numbers(url)
    assert numbers == {ids[0]: 1, ids[1]: 2, ids[2]: 3}
    assert _counter(url) == 3


def test_0016_empty_database_gets_counter_zero(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0016", monkeypatch)

    assert _counter(url) == 0


def test_0016_downgrade_and_upgrade_roundtrip(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0015", monkeypatch)
    ids = _seed_players(url)
    _alembic(url, command.upgrade, "0016", monkeypatch)

    _alembic(url, command.downgrade, "0015", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            tables = set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()
    assert "registry_player_numbers" not in tables
    assert "registry_number_counter" not in tables

    _alembic(url, command.upgrade, "0016", monkeypatch)
    assert _numbers(url) == {ids[0]: 1, ids[1]: 2, ids[2]: 3}
    assert _counter(url) == 3


def test_0016_skips_no_other_tables(tmp_path, monkeypatch):
    """Only the module's two new tables are touched."""
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0015", monkeypatch)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            before = set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()

    _alembic(url, command.upgrade, "0016", monkeypatch)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            after = set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()

    assert after - before == {"registry_player_numbers", "registry_number_counter"}
