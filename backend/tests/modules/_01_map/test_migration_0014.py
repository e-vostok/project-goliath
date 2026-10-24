"""
Migration 0014 tests on a real SQLite file database (Spec 01_map 1.3 —
the ownership journal gains the new owner's short name).

A database standing at revision 0013 is seeded with three journal
rows: a claim on a live nation, a claim on a vanished nation and a
release. Upgrading to 0014 must backfill ``new_nation_short_name``
from the live nation, fall back to the stored full name when it is
gone and leave releases NULL. Downgrade drops the column and a second
upgrade re-adds it.
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


def _seed_log(url: str) -> None:
    nation_id, gone_id = str(uuid.uuid4()), str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO players (id, vk_user_id) VALUES (:id, 42424401)"),
                {"id": owner_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations "
                    "(id, owner_player_id, name, color_hex, short_name, "
                    " created_at, created_turn) "
                    "VALUES (:id, :owner, 'Южный Союз', '#123456', 'ЮжСоюз',"
                    " '2026-09-01 00:00:00', 0)"
                ),
                {"id": nation_id, "owner": owner_id},
            )
            conn.execute(
                sa.text("INSERT INTO provinces (id, kind) VALUES (1001, 'LAND')")
            )
            rows = [
                # Claim on a live nation.
                (1, nation_id, "Южный Союз", "#123456"),
                # Claim on a nation that later vanished.
                (2, gone_id, "Павшее Королевство", "#654321"),
            ]
            for turn, nid, nname, ncolor in rows:
                conn.execute(
                    sa.text(
                        "INSERT INTO map_ownership_log "
                        "(province_id, turn_number, new_nation_id, "
                        " new_nation_name, new_nation_color, created_at) "
                        "VALUES (1001, :turn, :nid, :nname, :ncolor,"
                        " '2026-09-01 01:00:00')"
                    ),
                    {"turn": turn, "nid": nid, "nname": nname, "ncolor": ncolor},
                )
            # Release row — all new_nation_* fields NULL.
            conn.execute(
                sa.text(
                    "INSERT INTO map_ownership_log "
                    "(province_id, turn_number, prev_nation_id, created_at) "
                    "VALUES (1001, 3, :prev, '2026-09-02 01:00:00')"
                ),
                {"prev": nation_id},
            )
    finally:
        engine.dispose()


def test_0014_backfills_short_name(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0013", monkeypatch)
    _seed_log(url)

    _alembic(url, command.upgrade, "0014", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text(
                        "SELECT turn_number, new_nation_short_name "
                        "FROM map_ownership_log ORDER BY turn_number"
                    )
                ).all()
            )
    finally:
        engine.dispose()

    # Live nation → its short name; vanished → stored full name;
    # release stays NULL.
    assert rows == {1: "ЮжСоюз", 2: "Павшее Королевство", 3: None}


def test_0014_downgrade_upgrade_roundtrip(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0013", monkeypatch)
    _seed_log(url)
    _alembic(url, command.upgrade, "0014", monkeypatch)

    _alembic(url, command.downgrade, "0013", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            cols = {
                c["name"] for c in sa.inspect(conn).get_columns("map_ownership_log")
            }
    finally:
        engine.dispose()
    assert "new_nation_short_name" not in cols

    _alembic(url, command.upgrade, "0014", monkeypatch)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            cols = {
                c["name"] for c in sa.inspect(conn).get_columns("map_ownership_log")
            }
            refilled = dict(
                conn.execute(
                    sa.text(
                        "SELECT turn_number, new_nation_short_name "
                        "FROM map_ownership_log"
                    )
                ).all()
            )
    finally:
        engine.dispose()
    assert "new_nation_short_name" in cols
    assert refilled == {1: "ЮжСоюз", 2: "Павшее Королевство", 3: None}
