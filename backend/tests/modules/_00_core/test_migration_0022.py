"""
Migration 0022 tests on a real SQLite file database (0.14.0 unit 4).

Upgrading 0021 -> 0022 adds 1 to every stored game turn —
``game_clock.current_turn``, ``nations.created_turn``,
``tick_log.turn_number``, ``scheduled_actions.turn_number``,
``map_ownership_log.turn_number``, ``bot_state.last_digest_turn`` —
while the calendar formula starts subtracting 1, so every game date
computed after the upgrade equals the date the old formula gave for
the old number. Server defaults (``current_turn``,
``last_digest_turn``) move 0 -> 1 and ``ck_nations_created_turn_min``
becomes ``created_turn >= 1``. Downgrade restores the numbers and the
old defaults/check.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig

BACKEND_DIR = Path(__file__).resolve().parents[3]

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

# Turns stored at 0021: old numbering, first turn is 0.
CLOCK_TURN = 3
NATION_TURN = 0  # founded on the old first turn — proves 0 -> 1
TICK_TURN = 3
ACTION_TURN = 4
MAP_TURN = 2
BOT_TURN = 2


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    verb(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _old_game_date(turn: int) -> date:
    """The pre-0022 formula: epoch + N_turn * months_per_turn."""
    epoch = CORE_CONFIG.calendar.epoch_start_date
    total = (
        epoch.year * 12
        + (epoch.month - 1)
        + turn * CORE_CONFIG.calendar.months_per_turn
    )
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


def _exec(url: str, *statements: str) -> None:
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _seed(url: str) -> None:
    """One row per turn-carrying table, at 0021 numbering."""
    _exec(
        url,
        "INSERT INTO players (id, vk_user_id, created_at) "
        "VALUES ('p1', 42424321, '2026-10-01 00:00:00')",
        f"UPDATE game_clock SET current_turn = {CLOCK_TURN}",
        "INSERT INTO nations (id, owner_player_id, name, name_key, "
        "color_hex, short_name, short_name_key, created_at, created_turn) "
        f"VALUES ('n1', 'p1', 'Рим', 'рим', '#0C7CF4', 'RIM', 'rim', "
        f"'2026-10-01 00:00:00', {NATION_TURN})",
        "INSERT INTO tick_log (turn_number, started_at) VALUES "
        f"({TICK_TURN}, '2026-10-02 00:00:00')",
        "INSERT INTO scheduled_actions (id, module_slug, action_type, "
        "payload, turn_number, created_at) VALUES "
        f"('sa1', '00_core', 'test', '{{}}', {ACTION_TURN}, "
        "'2026-10-02 00:00:00')",
        "INSERT INTO provinces (id) VALUES (101)",
        "INSERT INTO map_ownership_log (province_id, turn_number, "
        f"created_at) VALUES (101, {MAP_TURN}, '2026-10-02 00:00:00')",
        f"UPDATE bot_state SET last_digest_turn = {BOT_TURN}",
    )


def _turns(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return {
                "clock": conn.execute(
                    sa.text("SELECT current_turn FROM game_clock WHERE id = 1")
                ).scalar_one(),
                "nation": conn.execute(
                    sa.text("SELECT created_turn FROM nations WHERE id = 'n1'")
                ).scalar_one(),
                "tick": conn.execute(
                    sa.text("SELECT turn_number FROM tick_log")
                ).scalar_one(),
                "action": conn.execute(
                    sa.text("SELECT turn_number FROM scheduled_actions")
                ).scalar_one(),
                "map": conn.execute(
                    sa.text("SELECT turn_number FROM map_ownership_log")
                ).scalar_one(),
                "bot": conn.execute(
                    sa.text("SELECT last_digest_turn FROM bot_state WHERE id = 1")
                ).scalar_one(),
            }
    finally:
        engine.dispose()


def _defaults_and_check(url: str) -> dict:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            clock_default = {
                c["name"]: c for c in insp.get_columns("game_clock")
            }["current_turn"]["default"]
            bot_default = {
                c["name"]: c for c in insp.get_columns("bot_state")
            }["last_digest_turn"]["default"]
            checks = {
                c["name"]: c["sqltext"]
                for c in insp.get_check_constraints("nations")
            }
            return {
                "clock_default": clock_default,
                "bot_default": bot_default,
                "check": checks["ck_nations_created_turn_min"],
            }
    finally:
        engine.dispose()


def test_0022_shifts_turns_and_keeps_game_dates(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0021", monkeypatch)
    _seed(url)

    # The dates the world shows today, under the old formula.
    world_date_before = _old_game_date(CLOCK_TURN)
    nation_date_before = _old_game_date(NATION_TURN)

    _alembic(url, command.upgrade, "0022", monkeypatch)

    turns = _turns(url)
    assert turns == {
        "clock": CLOCK_TURN + 1,
        "nation": NATION_TURN + 1,
        "tick": TICK_TURN + 1,
        "action": ACTION_TURN + 1,
        "map": MAP_TURN + 1,
        "bot": BOT_TURN + 1,
    }
    # New numbers + new formula = the very same game dates.
    assert compute_game_date(turns["clock"], CORE_CONFIG) == world_date_before
    assert compute_game_date(turns["nation"], CORE_CONFIG) == nation_date_before

    shape = _defaults_and_check(url)
    assert "1" in str(shape["clock_default"])
    assert "1" in str(shape["bot_default"])
    assert "created_turn>=1" in shape["check"].replace(" ", "")


def test_0022_downgrade_restores_numbers_and_shape(tmp_path, monkeypatch):
    url = _db_url(tmp_path)
    _alembic(url, command.upgrade, "0021", monkeypatch)
    _seed(url)
    _alembic(url, command.upgrade, "0022", monkeypatch)
    assert _turns(url)["clock"] == CLOCK_TURN + 1

    _alembic(url, command.downgrade, "0021", monkeypatch)

    turns = _turns(url)
    assert turns == {
        "clock": CLOCK_TURN,
        "nation": NATION_TURN,
        "tick": TICK_TURN,
        "action": ACTION_TURN,
        "map": MAP_TURN,
        "bot": BOT_TURN,
    }
    shape = _defaults_and_check(url)
    assert "0" in str(shape["clock_default"])
    assert "0" in str(shape["bot_default"])
    assert "created_turn>=0" in shape["check"].replace(" ", "")

    # A second upgrade shifts the same values again.
    _alembic(url, command.upgrade, "0022", monkeypatch)
    assert _turns(url)["clock"] == CLOCK_TURN + 1
