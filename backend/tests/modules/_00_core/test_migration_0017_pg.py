"""
Migration 0017 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0017.py but against the dedicated
*_test database — the column drops and the nullable re-adds run
through ``batch_alter_table`` on the real dialect.

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


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _upgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    command.downgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _columns(url: str, table: str) -> dict[str, dict]:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            return {c["name"]: c for c in sa.inspect(conn).get_columns(table)}
    finally:
        engine.dispose()


def test_0017_drops_catalog_columns_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0016", monkeypatch)

    nations_before = _columns(wiped_pg, "nations")
    orders_before = _columns(wiped_pg, "orders")
    assert {"flag_id", "portrait_id"} <= set(nations_before)
    assert "nation_flag_id" in orders_before

    _upgrade(wiped_pg, "0017", monkeypatch)

    nations = _columns(wiped_pg, "nations")
    orders = _columns(wiped_pg, "orders")
    assert "flag_id" not in nations
    assert "portrait_id" not in nations
    assert "nation_flag_id" not in orders
    assert set(nations) == set(nations_before) - {"flag_id", "portrait_id"}
    assert set(orders) == set(orders_before) - {"nation_flag_id"}


def test_0017_downgrade_restores_nullable_columns_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0016", monkeypatch)
    _upgrade(wiped_pg, "0017", monkeypatch)

    _downgrade(wiped_pg, "0016", monkeypatch)

    nations = _columns(wiped_pg, "nations")
    orders = _columns(wiped_pg, "orders")
    assert nations["flag_id"]["nullable"] is True
    assert nations["portrait_id"]["nullable"] is True
    assert orders["nation_flag_id"]["nullable"] is True

    _upgrade(wiped_pg, "0017", monkeypatch)
    nations = _columns(wiped_pg, "nations")
    orders = _columns(wiped_pg, "orders")
    assert "flag_id" not in nations
    assert "portrait_id" not in nations
    assert "nation_flag_id" not in orders
