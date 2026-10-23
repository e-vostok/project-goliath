"""
Migration 0014 tests on real PostgreSQL (module 01_map).

Same contract as test_migration_0014.py but against the dedicated
*_test database — the backfill UPDATE…SELECT runs on the real dialect.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

import uuid
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


def _seed_log(url: str) -> None:
    nation_id, gone_id = str(uuid.uuid4()), str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO players (id, vk_user_id) VALUES (:id, 42424402)"),
                {"id": owner_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, short_name, "
                    " created_at, created_turn) "
                    "VALUES (:id, :owner, 'Южный Союз', '#123456', 'ЮжСоюз',"
                    " now(), 0)"
                ),
                {"id": nation_id, "owner": owner_id},
            )
            conn.execute(
                sa.text("INSERT INTO provinces (id, kind) VALUES (1001, 'LAND')")
            )
            for turn, nid, nname, ncolor in (
                (1, nation_id, "Южный Союз", "#123456"),
                (2, gone_id, "Павшее Королевство", "#654321"),
            ):
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, new_nation_id, "
                        " new_nation_name, new_nation_color, created_at) "
                        "VALUES (1001, :turn, :nid, :nname, :ncolor, now())"
                    ),
                    {"turn": turn, "nid": nid, "nname": nname, "ncolor": ncolor},
                )
            conn.execute(
                sa.text(
                    "INSERT INTO map_ownership_log "
                    "(province_id, turn_number, prev_nation_id, created_at) "
                    "VALUES (1001, 3, :prev, now())"
                ),
                {"prev": nation_id},
            )
    finally:
        engine.dispose()


def test_0014_backfills_short_name_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0013", monkeypatch)
    _seed_log(wiped_pg)

    _upgrade(wiped_pg, "0014", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text(
                        "SELECT turn_number, new_nation_short_name "
                        "FROM map_ownership_log"
                    )
                ).all()
            )
    finally:
        engine.dispose()

    assert rows == {1: "ЮжСоюз", 2: "Павшее Королевство", 3: None}


def test_0014_downgrade_upgrade_roundtrip_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0013", monkeypatch)
    _seed_log(wiped_pg)
    _upgrade(wiped_pg, "0014", monkeypatch)

    _downgrade(wiped_pg, "0013", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            cols = {
                c["name"] for c in sa.inspect(conn).get_columns("map_ownership_log")
            }
    finally:
        engine.dispose()
    assert "new_nation_short_name" not in cols

    _upgrade(wiped_pg, "0014", monkeypatch)
    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            cols = {
                c["name"] for c in sa.inspect(conn).get_columns("map_ownership_log")
            }
    finally:
        engine.dispose()
    assert "new_nation_short_name" in cols
