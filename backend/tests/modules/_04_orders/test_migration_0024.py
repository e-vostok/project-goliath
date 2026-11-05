"""
Migration 0024 tests on a real SQLite file database (0.14.0 unit 7a).

Upgrading 0023 -> 0024 adds ``orders.refused_judge_ids`` (JSON, NOT
NULL, default ``[]``) and ``orders.assignment_no`` (Integer, NOT NULL,
default 1) with the ``ck_orders_assignment_no_positive`` CHECK;
existing rows get both defaults. Downgrade drops the CHECK and the
columns.
"""

from __future__ import annotations

from pathlib import Path

import pytest
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


def _schema(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            return {
                "columns": {c["name"]: c for c in insp.get_columns(TABLE)},
                "checks": {
                    c["name"]: c["sqltext"] for c in insp.get_check_constraints(TABLE)
                },
            }
    finally:
        engine.dispose()


def _seed_order(url: str) -> None:
    """One valid order row without the new columns filled — the
    defaults must cover it."""
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES ('p1', 42424424, '2026-11-01 00:00:00')"
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
                    "'https://vk.com/@x', '2026-11-01 00:00:00')"
                )
            )
    finally:
        engine.dispose()


def test_0024_adds_refusal_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0023", monkeypatch)
    before = _schema(url)
    assert "refused_judge_ids" not in before["columns"]
    assert "assignment_no" not in before["columns"]

    _alembic(url, command.upgrade, "0024", monkeypatch)

    schema = _schema(url)
    assert schema["columns"]["refused_judge_ids"]["nullable"] is False
    assert schema["columns"]["assignment_no"]["nullable"] is False
    assert "ck_orders_assignment_no_positive" in schema["checks"]


def test_0024_defaults_and_check_bite(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0024", monkeypatch)
    _seed_order(url)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            refused, no = conn.execute(
                sa.text(
                    "SELECT refused_judge_ids, assignment_no "
                    "FROM orders WHERE id = 'o1'"
                )
            ).one()
        assert refused == "[]"
        assert no == 1
        with engine.begin() as conn:
            with pytest.raises(sa.exc.IntegrityError):
                conn.execute(
                    sa.text("UPDATE orders SET assignment_no = 0 WHERE id = 'o1'")
                )
    finally:
        engine.dispose()


def test_0024_downgrade_drops_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0024", monkeypatch)

    _alembic(url, command.downgrade, "0023", monkeypatch)
    schema = _schema(url)
    assert "refused_judge_ids" not in schema["columns"]
    assert "assignment_no" not in schema["columns"]
    assert "ck_orders_assignment_no_positive" not in schema["checks"]

    # A second upgrade recreates the same shape.
    _alembic(url, command.upgrade, "0024", monkeypatch)
    schema = _schema(url)
    assert "refused_judge_ids" in schema["columns"]
    assert "ck_orders_assignment_no_positive" in schema["checks"]
