"""
Migration 0008 tests on a real SQLite file database (Spec 03_registry
1.2 — module 03_registry Issue 1).

A database standing at revision 0007 is seeded with completed tick_log
rows and nations created before, between and after them; upgrading to
0008 must backfill ``nations.created_turn`` as the greatest COMPLETED
``turn_number`` whose ``finished_at`` is not later than the nation's
``created_at`` (a nation before any tick gets 0), then enforce NOT NULL
and the named CHECKs. Timestamps are seeded in both naive and
offset-suffixed spellings — the migration normalises both to UTC before
comparing.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _upgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def test_0008_backfills_created_turn(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _upgrade(url, "0007", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            # Completed ticks: game moved to turn 1 at 2026-09-01 and to
            # turn 5 at 2026-09-10 (finished_at in mixed spellings).
            conn.execute(
                sa.text(
                    "INSERT INTO tick_log "
                    "(turn_number, started_at, finished_at, status) "
                    "VALUES (1, '2026-09-01 00:00:00.000000', "
                    "        '2026-09-01 00:05:00.000000', 'COMPLETED'), "
                    "       (5, '2026-09-10 00:00:00.000000', "
                    "        '2026-09-10 00:05:00+00:00', 'COMPLETED')"
                )
            )
            # Not eligible: a FAILED row and a COMPLETED row without
            # finished_at — both later than every nation below.
            conn.execute(
                sa.text(
                    "INSERT INTO tick_log "
                    "(turn_number, started_at, finished_at, status) "
                    "VALUES (9, '2026-09-20 00:00:00.000000', "
                    "        '2026-09-20 00:05:00.000000', 'FAILED'), "
                    "       (12, '2026-09-25 00:00:00.000000', "
                    "        NULL, 'COMPLETED')"
                )
            )
            players_nations = [
                ("nation-early", "Early", "#0E0001",
                 "2026-08-01 12:00:00.000000"),        # before any tick
                ("nation-mid", "Mid", "#0E0002",
                 "2026-09-05 12:00:00+00:00"),        # between the ticks
                ("nation-late", "Late", "#0E0003",
                 "2026-09-15 12:00:00.000000"),       # after turn 5
            ]
            for nation_id, name, color, created in players_nations:
                player_id = str(uuid.uuid4())
                conn.execute(
                    sa.text(
                        "INSERT INTO players (id, vk_user_id) "
                        "VALUES (:pid, :vk)"
                    ),
                    {"pid": player_id, "vk": hash(name) % 10**9},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO nations "
                        "(id, owner_player_id, name, color_hex, "
                        " created_at) "
                        "VALUES (:nid, :pid, :name, :color, :created)"
                    ),
                    {
                        "nid": nation_id,
                        "pid": player_id,
                        "name": name,
                        "color": color,
                        "created": created,
                    },
                )
    finally:
        engine.dispose()

    _upgrade(url, "0008", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    sa.text("SELECT id, created_turn FROM nations")
                ).all()
            )
            insp = sa.inspect(conn)
            checks = {
                c["name"] for c in insp.get_check_constraints("nations")
            } | {c["name"] for c in insp.get_check_constraints("players")}
            created_col = {
                c["name"]: c for c in insp.get_columns("nations")
            }["created_turn"]
    finally:
        engine.dispose()

    assert rows == {
        "nation-early": 0,
        "nation-mid": 1,
        "nation-late": 5,
    }
    assert created_col["nullable"] is False
    assert {
        "ck_players_level_min",
        "ck_players_judge_rating_range",
        "ck_nations_created_turn_min",
    } <= checks
