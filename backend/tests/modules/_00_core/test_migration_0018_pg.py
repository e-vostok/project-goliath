"""
Migration 0018 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0018.py but against the dedicated
*_test database — the ``nation_images`` CREATE TABLE with its
constraints and index runs on the real dialect, including the
ON DELETE CASCADE / SET NULL clauses.

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

TABLE = "nation_images"

EXPECTED_COLUMNS = {
    "id",
    "nation_id",
    "kind",
    "sha256",
    "full_bytes",
    "thumb_bytes",
    "byte_size",
    "uploaded_by_player_id",
    "uploaded_at",
}


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


def _schema(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {
                "tables": set(insp.get_table_names()),
                "columns": (
                    {c["name"] for c in insp.get_columns(TABLE)}
                    if TABLE in insp.get_table_names()
                    else set()
                ),
                "uniques": (
                    {
                        u["name"]: u["column_names"]
                        for u in insp.get_unique_constraints(TABLE)
                    }
                    if TABLE in insp.get_table_names()
                    else {}
                ),
                "checks": (
                    {
                        c["name"]
                        for c in insp.get_check_constraints(TABLE)
                    }
                    if TABLE in insp.get_table_names()
                    else set()
                ),
                "fks": (
                    {
                        fk["name"]: (
                            fk["referred_table"],
                            fk["options"].get("ondelete"),
                        )
                        for fk in insp.get_foreign_keys(TABLE)
                    }
                    if TABLE in insp.get_table_names()
                    else {}
                ),
                "indexes": (
                    {
                        i["name"]: i["unique"]
                        for i in insp.get_indexes(TABLE)
                    }
                    if TABLE in insp.get_table_names()
                    else {}
                ),
            }
    finally:
        engine.dispose()


def test_0018_creates_nation_images_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0017", monkeypatch)
    before = _schema(wiped_pg)
    assert TABLE not in before["tables"]

    _upgrade(wiped_pg, "0018", monkeypatch)

    schema = _schema(wiped_pg)
    assert TABLE in schema["tables"]
    assert schema["columns"] == EXPECTED_COLUMNS
    assert schema["uniques"]["uq_nation_images_nation_kind"] == [
        "nation_id",
        "kind",
    ]
    assert "ck_nation_images_kind" in schema["checks"]
    assert schema["fks"]["fk_nation_images_nation_id"] == (
        "nations",
        "CASCADE",
    )
    assert schema["fks"]["fk_nation_images_uploaded_by_player_id"] == (
        "players",
        "SET NULL",
    )
    assert schema["indexes"]["ix_nation_images_sha256"] is False
    assert schema["tables"] == before["tables"] | {TABLE}


def test_0018_downgrade_drops_nation_images_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0018", monkeypatch)
    assert TABLE in _schema(wiped_pg)["tables"]

    _downgrade(wiped_pg, "0017", monkeypatch)
    assert TABLE not in _schema(wiped_pg)["tables"]

    _upgrade(wiped_pg, "0018", monkeypatch)
    assert TABLE in _schema(wiped_pg)["tables"]
