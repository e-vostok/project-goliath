"""
Migration 0006 tests on real PostgreSQL (module 01_map).

Same contract as test_migration_0006.py but against the dedicated
*_test database: real FK enforcement, real CHECK constraints, real
BIGINT autoincrement (GENERATED … ALWAYS? no — plain serial semantics
match the model's Integer-variant autoincrement).

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import IntegrityError

from tests.fixtures.postgres import _reset_public_schema, _sync_url, pg_url

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _sync(url: str) -> str:
    return _sync_url(url)


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync(pg_url))
    return pg_url


def _upgrade(url: str, target: str, monkeypatch) -> None:
    # env.py resolves DATABASE_URL; hand it the psycopg2 sync URL.
    monkeypatch.setenv("DATABASE_URL", _sync(url))
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync(url))
    command.downgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _connect(url: str):
    return sa.create_engine(_sync(url))


def _nation_owning(url: str, province_id: int) -> str:
    """Insert player + nation rows; assign them a province; return the
    nation id."""
    player_id = str(uuid.uuid4())
    nation_id = str(uuid.uuid4())
    engine = _connect(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id) "
                    "VALUES (:id, 42424202)"
                ),
                {"id": player_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, created_at) "
                    "VALUES (:id, :owner, 'Guard Nation', '#654321', :ts)"
                ),
                {
                    "id": nation_id,
                    "owner": player_id,
                    "ts": datetime.now(timezone.utc),
                },
            )
            if province_id:
                conn.execute(
                    sa.text(
                        "UPDATE provinces SET nation_id = :nid "
                        "WHERE id = :pid"
                    ),
                    {"nid": nation_id, "pid": province_id},
                )
    finally:
        engine.dispose()
    return nation_id


def test_upgrade_head_schema_and_data(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            provinces_cols = {
                c["name"] for c in insp.get_columns("provinces")
            }
            tables = insp.get_table_names()
            checks = {
                chk["name"]
                for chk in insp.get_check_constraints("provinces")
            }
            indexes = {
                idx["name"] for idx in insp.get_indexes("map_ownership_log")
            }
            log_fks = insp.get_foreign_keys("map_ownership_log")
            provinces = conn.execute(
                sa.text("SELECT COUNT(*) FROM provinces")
            ).scalar_one()
    finally:
        engine.dispose()

    assert "kind" in provinces_cols
    assert "ck_provinces_kind" in checks
    assert "ck_provinces_sea_unowned" in checks
    assert "map_ownership_log" in tables
    assert {"ix_map_log_province_turn", "ix_map_log_turn"} <= indexes
    assert [fk["referred_table"] for fk in log_fks] == ["provinces"]
    assert provinces == 0


def test_province_checks_enforced_on_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)
    nation_id = _nation_owning(wiped_pg, 0)

    engine = _connect(wiped_pg)
    try:
        # SEA owned → violates ck_provinces_sea_unowned.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO provinces (id, kind, nation_id) "
                        "VALUES (2001, 'SEA', :nid)"
                    ),
                    {"nid": nation_id},
                )
        # Invalid kind → violates ck_provinces_kind.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO provinces (id, kind, nation_id) "
                        "VALUES (1002, 'XXX', NULL)"
                    )
                )
        # SEA free and LAND owned → accepted.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO provinces (id, kind, nation_id) "
                    "VALUES (2002, 'SEA', NULL)"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO provinces (id, kind, nation_id) "
                    "VALUES (1001, 'LAND', :nid)"
                ),
                {"nid": nation_id},
            )
    finally:
        engine.dispose()


def test_owned_placeholder_aborts_upgrade(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0005", monkeypatch)
    _nation_owning(wiped_pg, 42)

    with pytest.raises(RuntimeError, match="сброс мира"):
        _upgrade(wiped_pg, "head", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            assert "kind" not in {
                c["name"] for c in insp.get_columns("provinces")
            }
            assert "map_ownership_log" not in insp.get_table_names()
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM provinces")
            ).scalar_one()
    finally:
        engine.dispose()
    assert count == 100


def test_downgrade_then_upgrade_roundtrip(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)
    _downgrade(wiped_pg, "0005", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            assert "kind" not in {
                c["name"] for c in insp.get_columns("provinces")
            }
            assert "map_ownership_log" not in insp.get_table_names()
            count = conn.execute(
                sa.text("SELECT COUNT(*) FROM provinces")
            ).scalar_one()
    finally:
        engine.dispose()
    assert count == 100

    _upgrade(wiped_pg, "head", monkeypatch)
    engine = _connect(wiped_pg)
    try:
        with engine.connect() as conn:
            assert "kind" in {
                c["name"] for c in sa.inspect(conn).get_columns("provinces")
            }
    finally:
        engine.dispose()


def test_log_inserts_get_distinct_ids(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO provinces (id, kind) VALUES (1001, 'LAND')")
            )
            for turn in (1, 2):
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, created_at) "
                        "VALUES (1001, :turn, now())"
                    ),
                    {"turn": turn},
                )
            ids = [
                row[0]
                for row in conn.execute(
                    sa.text("SELECT id FROM map_ownership_log ORDER BY id")
                )
            ]
    finally:
        engine.dispose()
    assert len(ids) == 2 and ids[0] != ids[1]


def test_log_check_constraint_on_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "head", monkeypatch)

    engine = _connect(wiped_pg)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO provinces (id, kind) VALUES (1001, 'LAND')")
            )
        # Partially filled new_nation_* triple → ck_log_new_nation_consistent.
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, new_nation_id, created_at) "
                        "VALUES (1001, 1, :nid, now())"
                    ),
                    {"nid": str(uuid.uuid4())},
                )
        # Fully filled triple → accepted.
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO map_ownership_log "
                    "(province_id, turn_number, prev_nation_id, "
                    " new_nation_id, new_nation_name, new_nation_color, "
                    " created_at) "
                    "VALUES (1001, 2, :prev, :new, 'N', '#AABBCC', now())"
                ),
                {"prev": str(uuid.uuid4()), "new": str(uuid.uuid4())},
            )
    finally:
        engine.dispose()
