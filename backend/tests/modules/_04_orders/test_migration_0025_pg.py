"""
Migration 0025 tests on real PostgreSQL (0.14.0 unit 7b).

Same contract as test_migration_0025.py against the dedicated *_test
database: ``orders.term_exempt`` (Boolean, NOT NULL, default
``false``); rows judged, undecided and already past ``deadline_at``
at the upgrade moment are grandfathered to ``true``; rows still in
term keep ``false``; downgrade drops the column.

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


def _columns(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {c["name"]: c for c in insp.get_columns(TABLE)}
    finally:
        engine.dispose()


def _seed_orders(url: str) -> None:
    """The grandfather matrix: past deadline, still in term,
    judge-less and decided."""
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424425, now()), "
                    "('p2', 42424426, now())"
                )
            )
            conn.execute(
                sa.text(
                    "INSERT INTO orders (id, number, author_player_id, "
                    "client_request_id, nation_id, nation_name, "
                    "nation_color, nation_short_name, title, summary, "
                    "article_url, submitted_at, judge_player_id, "
                    "distributed_at, reminder_at, deadline_at, "
                    "verdict_title, verdict_summary, verdict_url, "
                    "verdict_at) VALUES "
                    "('o_overdue', 1, 'p1', 'cr1', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', now() - interval '80 hours', "
                    "'p2', now() - interval '80 hours', "
                    "now() - interval '26 hours', "
                    "now() - interval '8 hours', NULL, NULL, NULL, NULL), "
                    "('o_due', 2, 'p1', 'cr2', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', now() - interval '1 hours', "
                    "'p2', now() - interval '1 hours', "
                    "now() + interval '53 hours', "
                    "now() + interval '71 hours', NULL, NULL, NULL, NULL), "
                    "('o_waiting', 3, 'p1', 'cr3', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', now() - interval '1 hours', "
                    "NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
                    "('o_decided', 4, 'p1', 'cr4', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', now() - interval '80 hours', "
                    "'p2', now() - interval '80 hours', "
                    "now() - interval '26 hours', "
                    "now() - interval '8 hours', 'Вердикт', "
                    "'Суть вердикта', 'https://vk.com/@y', "
                    "now() - interval '10 hours')"
                )
            )
    finally:
        engine.dispose()


def _flags(url: str) -> dict[str, bool]:
    engine = sa.create_engine(_sync_url(url))
    try:
        with engine.connect() as conn:
            return {
                row[0]: row[1]
                for row in conn.execute(
                    sa.text("SELECT id, term_exempt FROM orders")
                ).all()
            }
    finally:
        engine.dispose()


def test_0025_adds_term_exempt_column_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)
    assert "term_exempt" not in _columns(wiped_pg)

    _alembic(wiped_pg, command.upgrade, "0025", monkeypatch)

    column = _columns(wiped_pg)["term_exempt"]
    assert column["nullable"] is False
    assert column["default"] is not None


def test_0025_grandfathers_already_overdue_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0024", monkeypatch)
    _seed_orders(wiped_pg)

    _alembic(wiped_pg, command.upgrade, "0025", monkeypatch)

    assert _flags(wiped_pg) == {
        "o_overdue": True,
        "o_due": False,
        "o_waiting": False,
        "o_decided": False,
    }


def test_0025_downgrade_drops_column_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0025", monkeypatch)

    _alembic(wiped_pg, command.downgrade, "0024", monkeypatch)
    assert "term_exempt" not in _columns(wiped_pg)

    _alembic(wiped_pg, command.upgrade, "0025", monkeypatch)
    assert "term_exempt" in _columns(wiped_pg)
