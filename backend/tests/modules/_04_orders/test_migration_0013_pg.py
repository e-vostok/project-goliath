"""
Migration 0013 tests on real PostgreSQL (module 04_orders).

Same contract as test_migration_0013.py but against the dedicated
*_test database — the backfill UPDATE…SELECT and the nullable→NOT NULL
alter run through ``batch_alter_table`` on the real dialect.

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


def _seed_orders(url: str) -> None:
    nation_id, gone_id = str(uuid.uuid4()), str(uuid.uuid4())
    author_id = str(uuid.uuid4())
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO players (id, vk_user_id) VALUES (:id, 42424302)"),
                {"id": author_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, short_name, "
                    " flag_id, created_at, created_turn) "
                    "VALUES (:id, :owner, 'Северная Лига', '#336699', 'СевЛига',"
                    " 'flag_placeholder_1', now(), 0)"
                ),
                {"id": nation_id, "owner": author_id},
            )
            for number, nid, nname in (
                (1, nation_id, "Северная Лига"),
                (2, gone_id, "Исчезнувшая Держава"),
            ):
                conn.execute(
                    sa.text(
                        "INSERT INTO orders "
                        "(id, number, author_player_id, client_request_id, "
                        " nation_id, nation_name, nation_color, title, summary, "
                        " article_url, submitted_at) "
                        "VALUES (:id, :num, :author, :req, :nid, :nname,"
                        " '#336699', 'П', 'С', 'https://vk.com/@o', now())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "num": number,
                        "author": author_id,
                        "req": str(uuid.uuid4()),
                        "nid": nid,
                        "nname": nname,
                    },
                )
    finally:
        engine.dispose()


def test_0013_backfills_snapshot_columns_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0012", monkeypatch)
    _seed_orders(wiped_pg)

    _upgrade(wiped_pg, "0013", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            rows = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    sa.text(
                        "SELECT number, nation_short_name, nation_flag_id FROM orders"
                    )
                ).all()
            }
            short_col = {c["name"]: c for c in sa.inspect(conn).get_columns("orders")}[
                "nation_short_name"
            ]
    finally:
        engine.dispose()

    assert rows == {
        1: ("СевЛига", "flag_placeholder_1"),
        2: ("Исчезнувшая Держава", None),
    }
    assert short_col["nullable"] is False


def test_0013_downgrade_upgrade_roundtrip_pg(wiped_pg, monkeypatch):
    _upgrade(wiped_pg, "0012", monkeypatch)
    _seed_orders(wiped_pg)
    _upgrade(wiped_pg, "0013", monkeypatch)

    _downgrade(wiped_pg, "0012", monkeypatch)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("orders")}
    finally:
        engine.dispose()
    assert "nation_short_name" not in cols
    assert "nation_flag_id" not in cols

    _upgrade(wiped_pg, "0013", monkeypatch)
    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("orders")}
    finally:
        engine.dispose()
    assert {"nation_short_name", "nation_flag_id"} <= cols
