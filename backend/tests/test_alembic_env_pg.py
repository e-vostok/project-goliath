"""
Alembic upgrade on real PostgreSQL with the asyncpg DATABASE_URL form
— exactly the shape ``.env.prod.example`` ships (FIX-ENV).

Regression for the env.py driver bug: it stripped ``+asyncpg``
textually, and SQLAlchemy 2.x resolves bare ``postgresql://`` to the
psycopg3 driver — not installed — so ``alembic upgrade head`` died with
``ModuleNotFoundError: psycopg`` before running a single migration.
env.py must convert the URL to the installed sync driver (psycopg2).

postgres marker: needs DATABASE_URL_TEST (see tests/fixtures/postgres.py)
— the target schema is dropped and rebuilt, never a shared database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from tests.fixtures import postgres as pg_fixtures
from tests.fixtures.postgres import pg_url  # noqa: F401 — fixture

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_upgrade_head_accepts_asyncpg_database_url(pg_url, monkeypatch):
    """DATABASE_URL in the asyncpg form migrates the wiped test schema
    to head and seeds the game_clock singleton."""
    # Fresh empty schema: the upgrade must create everything itself.
    pg_fixtures._reset_public_schema(pg_fixtures._sync_url(pg_url))
    monkeypatch.setenv("DATABASE_URL", pg_url)

    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

    engine = sa.create_engine(pg_fixtures._sync_url(pg_url))
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            clock_rows = conn.execute(
                sa.text("SELECT count(*) FROM game_clock WHERE id = 1")
            ).scalar_one()
    finally:
        engine.dispose()
    assert version == "0007"
    assert clock_rows == 1
