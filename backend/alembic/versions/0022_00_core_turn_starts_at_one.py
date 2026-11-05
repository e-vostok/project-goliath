"""
Turn numbering starts at 1 (0.14.0 unit 4).

Players count turns from 1: the first turn of a world is turn 1
(January 2040), not turn 0. ``compute_game_date`` now subtracts 1 in
its month formula — epoch + (N_turn - 1) * months_per_turn — so every
stored game turn is shifted +1 here and every game date that exists
today stays exactly the same after deploy.

The shift covers every column that holds a game turn:
``game_clock.current_turn``, ``nations.created_turn``,
``tick_log.turn_number``, ``scheduled_actions.turn_number``,
``map_ownership_log.turn_number`` and ``bot_state.last_digest_turn``
(a plain ``+ 1`` leaves NULLs NULL). Data moves BEFORE the tightened
``ck_nations_created_turn_min`` is recreated — a nation founded on
the old first turn stored 0, which ``created_turn >= 1`` would
reject.

Schema changes alongside: ``game_clock.current_turn`` and
``bot_state.last_digest_turn`` server defaults go 0 -> 1 (a fresh
world/bot state starts at turn 1), and
``ck_nations_created_turn_min`` becomes ``created_turn >= 1``.
``batch_alter_table`` keeps SQLite and PostgreSQL on the same path.
Downgrade restores the old constraints/defaults first, then subtracts
1 from every stored turn again.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

# (table, column) — every stored game turn, shifted +1 on upgrade.
_TURN_COLUMNS = (
    ("game_clock", "current_turn"),
    ("nations", "created_turn"),
    ("tick_log", "turn_number"),
    ("scheduled_actions", "turn_number"),
    ("map_ownership_log", "turn_number"),
    ("bot_state", "last_digest_turn"),
)


def _shift_turns(delta: int) -> None:
    """Add ``delta`` to every stored game turn; NULL stays NULL."""
    for table, column in _TURN_COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = {column} + {delta:d}")


def _reshape(default: str, check: str) -> None:
    """Server defaults and the created_turn lower bound for one numbering."""
    with op.batch_alter_table("game_clock") as batch_op:
        batch_op.alter_column(
            "current_turn",
            existing_type=sa.BigInteger(),
            server_default=default,
        )
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_constraint("ck_nations_created_turn_min", type_="check")
        batch_op.create_check_constraint("ck_nations_created_turn_min", check)
    with op.batch_alter_table("bot_state") as batch_op:
        batch_op.alter_column(
            "last_digest_turn",
            existing_type=sa.Integer(),
            server_default=default,
        )


def upgrade() -> None:
    # Data first: stored 0s become 1s, so the recreated check
    # ``created_turn >= 1`` sees no violating row.
    _shift_turns(+1)
    _reshape("1", "created_turn >= 1")


def downgrade() -> None:
    # Schema first: the relaxed check must be back before any 0 returns.
    _reshape("0", "created_turn >= 0")
    _shift_turns(-1)
