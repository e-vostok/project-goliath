"""
Migration 0016 tests on real PostgreSQL (module 03_registry, unit 11).

Same contract as test_migration_0016.py — the backfill and counter on
the real dialect — plus the advisory-lock issuing path: on PostgreSQL
``ensure_player_numbers`` runs under ``pg_advisory_xact_lock``, and a
racing call must still produce unique numbers.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from modules._03_registry.service import ensure_player_numbers
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


def _seed_players(url: str, count: int = 3) -> list[str]:
    ids = [str(uuid.uuid4()) for _ in range(count)]
    engine = sa.create_engine(_sync_url(url))
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
                        "vk": 560001 + i,
                        "created": datetime(2026, 9, i + 1, 12, tzinfo=UTC),
                    },
                )
    finally:
        engine.dispose()
    return ids


def _numbers(url: str) -> dict[str, int]:
    engine = sa.create_engine(_sync_url(url))
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
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT last_number FROM registry_number_counter WHERE id = 1")
            ).scalar_one()
    finally:
        engine.dispose()


def test_0016_backfills_positions_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0015", monkeypatch)
    ids = _seed_players(wiped_pg)

    _upgrade(wiped_pg, "0016", monkeypatch)

    assert _numbers(wiped_pg) == {ids[0]: 1, ids[1]: 2, ids[2]: 3}
    assert _counter(wiped_pg) == 3


def test_0016_empty_counter_and_roundtrip_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0016", monkeypatch)
    assert _counter(wiped_pg) == 0

    _downgrade(wiped_pg, "0015", monkeypatch)
    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            tables = set(sa.inspect(conn).get_table_names())
    finally:
        engine.dispose()
    assert "registry_player_numbers" not in tables

    _upgrade(wiped_pg, "0016", monkeypatch)
    assert _counter(wiped_pg) == 0


def test_ensure_runs_under_advisory_lock_pg(wiped_pg, monkeypatch):
    """On the postgresql dialect ensure takes the module advisory lock
    and two racing calls still produce unique numbers."""
    _upgrade(wiped_pg, "head", monkeypatch)
    ids = _seed_players(wiped_pg)

    engine = create_async_engine(wiped_pg)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        results = asyncio.run(_collect(maker))
        merged = results[0] | results[1]
        assert sorted(merged.values()) == [1, 2, 3]
    finally:
        asyncio.run(engine.dispose())

    assert _counter(wiped_pg) == 3


async def _collect(maker) -> list[dict]:
    async def _run():
        async with maker() as session:
            return await ensure_player_numbers(session)

    return list(await asyncio.gather(_run(), _run()))
