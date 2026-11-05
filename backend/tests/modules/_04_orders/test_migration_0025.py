"""
Migration 0025 tests on a real SQLite file database (0.14.0 unit 7b).

Upgrading 0024 -> 0025 adds ``orders.term_exempt`` (Boolean, NOT
NULL, default ``false``) and grandfathers the rows already past
their deadline at the upgrade moment — judge set, no verdict,
``deadline_at`` earlier than now — to ``term_exempt = true`` so the
first worker pass after the deploy fines nobody in bulk. Rows still
inside their term keep ``false``. Downgrade drops the column.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]

TABLE = "orders"


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _columns(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {c["name"]: c for c in insp.get_columns(TABLE)}
    finally:
        engine.dispose()


def _seed_orders(url: str) -> None:
    """Four orders at the 0024 shape: one past its deadline, one still
    in term, one judge-less and one decided — the full grandfather
    matrix."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424425, '2026-11-01 00:00:00'), "
                    "('p2', 42424426, '2026-11-01 00:00:00')"
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
                    "'https://vk.com/@x', '2026-01-01 00:00:00', "
                    "'p2', '2026-01-01 00:00:00', '2026-01-02 00:00:00', "
                    "'2026-01-03 00:00:00', NULL, NULL, NULL, NULL), "
                    "('o_due', 2, 'p1', 'cr2', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', '2026-01-01 00:00:00', "
                    "'p2', '2026-01-01 00:00:00', '2030-01-02 00:00:00', "
                    "'2030-01-03 00:00:00', NULL, NULL, NULL, NULL), "
                    "('o_waiting', 3, 'p1', 'cr3', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', '2026-01-01 00:00:00', "
                    "NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL), "
                    "('o_decided', 4, 'p1', 'cr4', 'n1', 'Нация', "
                    "'#112233', 'Нац', 'Приказ', 'Суть приказа', "
                    "'https://vk.com/@x', '2026-01-01 00:00:00', "
                    "'p2', '2026-01-01 00:00:00', '2026-01-02 00:00:00', "
                    "'2026-01-03 00:00:00', 'Вердикт', 'Суть вердикта', "
                    "'https://vk.com/@y', '2026-01-02 00:00:00')"
                )
            )
    finally:
        engine.dispose()


def _flags(url: str) -> dict[str, int]:
    engine = sa.create_engine(url)
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


def test_0025_adds_term_exempt_column(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0024", monkeypatch)
    assert "term_exempt" not in _columns(url)

    _alembic(url, command.upgrade, "0025", monkeypatch)

    column = _columns(url)["term_exempt"]
    assert column["nullable"] is False
    assert column["default"] is not None


def test_0025_grandfathers_already_overdue(tmp_path, monkeypatch):
    """The deploy-time matrix: judged and past deadline -> exempt;
    judged and still in term, judge-less or decided -> enforced."""
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0024", monkeypatch)
    _seed_orders(url)

    _alembic(url, command.upgrade, "0025", monkeypatch)

    assert _flags(url) == {
        "o_overdue": 1,
        "o_due": 0,
        "o_waiting": 0,
        "o_decided": 0,
    }


def test_0025_downgrade_drops_column(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0025", monkeypatch)

    _alembic(url, command.downgrade, "0024", monkeypatch)
    assert "term_exempt" not in _columns(url)

    # A second upgrade recreates the same shape.
    _alembic(url, command.upgrade, "0025", monkeypatch)
    assert "term_exempt" in _columns(url)
