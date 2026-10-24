"""
Migration 0013 tests on a real SQLite file database (Spec 04_orders
1.1 — the nation snapshot gains short name and flag id).

A database standing at revision 0012 is seeded with two orders: one
whose nation still exists and one whose nation has vanished. Upgrading
to 0013 must backfill ``orders.nation_short_name``/``nation_flag_id``
from the live nation and fall back to the stored full name (NULL flag)
when it is gone, then enforce NOT NULL on the short name. Downgrade
drops both columns and a second upgrade re-adds them.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _upgrade(url: str, target: str, monkeypatch) -> None:
    _alembic(url, command.upgrade, target, monkeypatch)


def _seed_orders(url: str) -> dict[str, str]:
    """One nation + one order on it, and one order whose nation is
    already gone. Returns the nation id."""
    nation_id, gone_id = str(uuid.uuid4()), str(uuid.uuid4())
    author_id = str(uuid.uuid4())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO players (id, vk_user_id) VALUES (:id, 42424301)"),
                {"id": author_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, short_name, "
                    " flag_id, created_at, created_turn) "
                    "VALUES (:id, :owner, 'Северная Лига', '#336699', 'СевЛига',"
                    " 'flag_placeholder_1', '2026-09-01 00:00:00', 0)"
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
                        " '#336699', 'П', 'С', 'https://vk.com/@o',"
                        " '2026-09-01 01:00:00')"
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
    return {"nation_id": nation_id, "gone_id": gone_id}


def test_0013_backfills_snapshot_columns(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0012", monkeypatch)
    _seed_orders(url)

    _upgrade(url, "0013", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text(
                        "SELECT number, nation_short_name || '|' ||"
                        " COALESCE(nation_flag_id, '<null>') FROM orders"
                    )
                ).all()
            )
            short_col = {c["name"]: c for c in sa.inspect(conn).get_columns("orders")}[
                "nation_short_name"
            ]
    finally:
        engine.dispose()

    # Live nation → its short name and flag id; vanished nation →
    # falls back to the stored full name, flag stays NULL.
    assert rows == {
        1: "СевЛига|flag_placeholder_1",
        2: "Исчезнувшая Держава|<null>",
    }
    assert short_col["nullable"] is False


def test_0013_downgrade_upgrade_roundtrip(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0012", monkeypatch)
    _seed_orders(url)
    _upgrade(url, "0013", monkeypatch)

    _alembic(url, command.downgrade, "0012", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("orders")}
    finally:
        engine.dispose()
    assert "nation_short_name" not in cols
    assert "nation_flag_id" not in cols

    _upgrade(url, "0013", monkeypatch)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            cols = {c["name"] for c in sa.inspect(conn).get_columns("orders")}
            refilled = dict(
                conn.execute(
                    sa.text("SELECT number, nation_short_name FROM orders")
                ).all()
            )
    finally:
        engine.dispose()
    assert {"nation_short_name", "nation_flag_id"} <= cols
    assert refilled == {1: "СевЛига", 2: "Исчезнувшая Держава"}
