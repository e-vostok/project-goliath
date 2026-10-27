"""
Migration 0017 tests on a real SQLite file database (Spec 00_core
Part 1 — the ready-made flag/portrait catalog is removed, 0.12.0
unit 4a).

Upgrading 0016 -> 0017 drops ``nations.flag_id``,
``nations.portrait_id`` and ``orders.nation_flag_id``; nothing else of
either table moves. Downgrade restores the three columns as nullable —
the schema returns, the dropped ids are not restored.
"""

from __future__ import annotations

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


def _upgrade(url: str, target: str, monkeypatch) -> None:
    _alembic(url, command.upgrade, target, monkeypatch)


def _columns(url: str, table: str) -> dict[str, dict]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return {c["name"]: c for c in sa.inspect(conn).get_columns(table)}
    finally:
        engine.dispose()


def test_0017_drops_catalog_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0016", monkeypatch)

    nations_before = _columns(url, "nations")
    orders_before = _columns(url, "orders")
    assert {"flag_id", "portrait_id"} <= set(nations_before)
    assert "nation_flag_id" in orders_before

    _upgrade(url, "0017", monkeypatch)

    nations = _columns(url, "nations")
    orders = _columns(url, "orders")
    assert "flag_id" not in nations
    assert "portrait_id" not in nations
    assert "nation_flag_id" not in orders
    # The rest of each table is untouched.
    assert set(nations) == set(nations_before) - {"flag_id", "portrait_id"}
    assert set(orders) == set(orders_before) - {"nation_flag_id"}


def test_0017_downgrade_restores_nullable_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0016", monkeypatch)
    _upgrade(url, "0017", monkeypatch)

    _alembic(url, command.downgrade, "0016", monkeypatch)

    nations = _columns(url, "nations")
    orders = _columns(url, "orders")
    assert nations["flag_id"]["nullable"] is True
    assert nations["portrait_id"]["nullable"] is True
    assert orders["nation_flag_id"]["nullable"] is True

    # A second upgrade drops them again cleanly.
    _upgrade(url, "0017", monkeypatch)
    nations = _columns(url, "nations")
    orders = _columns(url, "orders")
    assert "flag_id" not in nations
    assert "portrait_id" not in nations
    assert "nation_flag_id" not in orders
