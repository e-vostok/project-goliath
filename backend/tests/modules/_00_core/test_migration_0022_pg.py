"""
Migration 0022 tests on real PostgreSQL (module 00_core).

Same contract as test_migration_0022.py against the dedicated *_test
database: every stored game turn shifts +1 while the recomputed game
dates stay identical, the ``current_turn``/``last_digest_turn``
server defaults move to 1, ``ck_nations_created_turn_min`` becomes
``created_turn >= 1``, and the downgrade restores both the numbers
and the old shape.

Requires DATABASE_URL_TEST; wipes the public schema like pg_schema does.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from modules._00_core.calendar import compute_game_date
from modules._00_core.config_schema import CoreConfig
from tests.fixtures.postgres import (
    _reset_public_schema,
    _sync_url,
    pg_url,  # noqa: F401
)

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[3]

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

CLOCK_TURN = 3
NATION_TURN = 0  # founded on the old first turn — proves 0 -> 1
TICK_TURN = 3
ACTION_TURN = 4
MAP_TURN = 2
BOT_TURN = 2


@pytest.fixture
def wiped_pg(pg_url: str) -> str:
    """A wiped test database with no migrations applied."""
    _reset_public_schema(_sync_url(pg_url))
    return pg_url


def _alembic(url: str, verb, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _sync_url(url))
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
    engine = sa.create_engine(_sync_url(url))
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
        "VALUES ('p1', 42424321, now())",
        f"UPDATE game_clock SET current_turn = {CLOCK_TURN}",
        "INSERT INTO nations (id, owner_player_id, name, name_key, "
        "color_hex, short_name, short_name_key, created_at, created_turn) "
        f"VALUES ('n1', 'p1', 'Рим', 'рим', '#0C7CF4', 'RIM', 'rim', "
        f"now(), {NATION_TURN})",
        "INSERT INTO tick_log (turn_number, started_at) VALUES "
        f"({TICK_TURN}, now())",
        "INSERT INTO scheduled_actions (id, module_slug, action_type, "
        "payload, turn_number, created_at) VALUES "
        f"('sa1', '00_core', 'test', '{{}}', {ACTION_TURN}, now())",
        "INSERT INTO provinces (id) VALUES (101)",
        "INSERT INTO map_ownership_log (province_id, turn_number, "
        f"created_at) VALUES (101, {MAP_TURN}, now())",
        f"UPDATE bot_state SET last_digest_turn = {BOT_TURN}",
    )


def _turns(url: str) -> dict:
    engine = sa.create_engine(_sync_url(url))
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
    engine = sa.create_engine(_sync_url(url))
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


def test_0022_shifts_turns_and_keeps_game_dates_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)
    _seed(wiped_pg)

    world_date_before = _old_game_date(CLOCK_TURN)
    nation_date_before = _old_game_date(NATION_TURN)

    _alembic(wiped_pg, command.upgrade, "0022", monkeypatch)

    turns = _turns(wiped_pg)
    assert turns == {
        "clock": CLOCK_TURN + 1,
        "nation": NATION_TURN + 1,
        "tick": TICK_TURN + 1,
        "action": ACTION_TURN + 1,
        "map": MAP_TURN + 1,
        "bot": BOT_TURN + 1,
    }
    assert compute_game_date(turns["clock"], CORE_CONFIG) == world_date_before
    assert compute_game_date(turns["nation"], CORE_CONFIG) == nation_date_before

    shape = _defaults_and_check(wiped_pg)
    assert "1" in str(shape["clock_default"])
    assert "1" in str(shape["bot_default"])
    # PostgreSQL renders the bound with a cast — compare loosely.
    assert ">=1" in shape["check"].replace(" ", "")


def test_0022_downgrade_restores_numbers_and_shape_pg(wiped_pg, monkeypatch):
    _alembic(wiped_pg, command.upgrade, "0021", monkeypatch)
    _seed(wiped_pg)
    _alembic(wiped_pg, command.upgrade, "0022", monkeypatch)
    assert _turns(wiped_pg)["clock"] == CLOCK_TURN + 1

    _alembic(wiped_pg, command.downgrade, "0021", monkeypatch)

    turns = _turns(wiped_pg)
    assert turns == {
        "clock": CLOCK_TURN,
        "nation": NATION_TURN,
        "tick": TICK_TURN,
        "action": ACTION_TURN,
        "map": MAP_TURN,
        "bot": BOT_TURN,
    }
    shape = _defaults_and_check(wiped_pg)
    assert "0" in str(shape["clock_default"])
    assert "0" in str(shape["bot_default"])
    assert ">=0" in shape["check"].replace(" ", "")

    _alembic(wiped_pg, command.upgrade, "0022", monkeypatch)
    assert _turns(wiped_pg)["clock"] == CLOCK_TURN + 1
