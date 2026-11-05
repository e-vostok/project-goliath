"""
Migration 0024 tests on real PostgreSQL (0.14.0 unit 7a).

Same contract as test_migration_0024.py against the dedicated *_test
database: ``orders.refused_judge_ids`` (JSON, NOT NULL, default
``[]``) and ``orders.assignment_no`` (Integer, NOT NULL, default 1)
with the named CHECK; existing rows take the defaults; downgrade
drops both.

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

TABLE = "orders"


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _schema(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {
                "columns": {c["name"]: c for c in insp.get_columns(TABLE)},
                "checks": {
                    c["name"]: c["sqltext"]
                    for c in insp.get_check_constraints(TABLE)
                },
            }
    finally:
        engine.dispose()


def _seed_order(url: str) -> None:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424424, now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO orders (id, number, author_player_id, "
                    "client_request_id, nation_id, nation_name, "
                    "nation_color, nation_short_name, title, summary, "
                    "article_url, submitted_at) VALUES "
                    "('o1', 1, 'p1', 'cr1', 'n1', 'Нация', '#112233', "
                    "'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', now())"
                )
            )
    finally:
        engine.dispose()


def test_0024_adds_refusal_columns_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0023", monkeypatch)
    assert "refused_judge_ids" not in _schema(wiped_pg)["columns"]

    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)

    schema = _schema(wiped_pg)
    assert schema["columns"]["refused_judge_ids"]["nullable"] is False
    assert schema["columns"]["assignment_no"]["nullable"] is False
    assert schema["columns"]["assignment_no"]["default"] is not None
    assert "ck_orders_assignment_no_positive" in schema["checks"]


def test_0024_defaults_and_check_bite_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)
    _seed_order(wiped_pg)

    engine = sa.create_engine(_sync_url(wiped_pg))
    try:
        with engine.connect() as conn:
            refused, no = conn.execute(
                sa.text(
                    "SELECT refused_judge_ids, assignment_no "
                    "FROM orders WHERE id = 'o1'"
                )
            ).one()
        assert refused == []
        assert no == 1
        with engine.begin() as conn:
            with pytest.raises(sa.exc.IntegrityError):
                conn.execute(
                    sa.text("UPDATE orders SET assignment_no = 0 WHERE id = 'o1'")
                )
    finally:
        engine.dispose()


def test_0024_downgrade_drops_columns_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)

    _alembic(wiped_pg, command.downgrade, "0023", monkeypatch)
    schema = _schema(wiped_pg)
    assert "refused_judge_ids" not in schema["columns"]
    assert "assignment_no" not in schema["columns"]

    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)
    assert "refused_judge_ids" in _schema(wiped_pg)["columns"]
