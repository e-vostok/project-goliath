"""
00_core extension for module 03_registry (Spec 1.2, Appendix B item B1/B2).

Additive — existing rows are preserved:

1. ``players.level`` — Integer NOT NULL, server_default 1, named CHECK
   ``ck_players_level_min`` (``level >= LEVEL_MIN``).
2. ``players.judge_rating`` — Integer NOT NULL, server_default 0, named
   CHECK ``ck_players_judge_rating_range``
   (``judge_rating BETWEEN JUDGE_RATING_MIN AND JUDGE_RATING_MAX``).
   The scale bounds come from ``modules._00_core.player_stats`` — they
   are model properties, not balance (Spec 0/D1).
3. ``nations.created_turn`` — BigInteger NOT NULL (no default after the
   backfill), named CHECK ``ck_nations_created_turn_min``
   (``created_turn >= 0``). INV-R9: immutable after creation.

``created_turn`` backfill (Spec 1.2): for every nation the greatest
``tick_log.turn_number`` among COMPLETED rows whose ``finished_at`` is
not later than the nation's ``created_at``; a nation created before any
completed tick gets 0. The comparison runs in Python over UTC-normalised
datetimes — naive values are read as UTC, aware ones converted — because
SQLite stores timestamps without a zone and PostgreSQL returns
timestamptz values already aware.

Downgrade drops the three CHECKs and the three columns.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import sqlalchemy as sa
from alembic import op

from modules._00_core.player_stats import (
    JUDGE_RATING_MAX,
    JUDGE_RATING_MIN,
    LEVEL_MIN,
)

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def _as_utc(value) -> datetime:
    """Normalise a DB timestamp to an aware UTC datetime for comparison.

    SQLAlchemy's SQLite DATETIME stores naive strings; PostgreSQL
    timestamptz returns aware datetimes. A raw string (any driver quirk)
    is parsed first; a naive value is read as UTC.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _backfill_created_turn() -> None:
    """Compute nations.created_turn from tick_log per Spec 1.2."""
    nations = sa.table(
        "nations",
        sa.Column("id", sa.String(length=36)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_turn", sa.BigInteger()),
    )
    tick_log = sa.table(
        "tick_log",
        sa.Column("turn_number", sa.BigInteger()),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(length=16)),
    )
    conn = op.get_bind()

    completed = [
        (_as_utc(finished_at), turn_number)
        for turn_number, finished_at in conn.execute(
            sa.select(tick_log.c.turn_number, tick_log.c.finished_at)
            .where(tick_log.c.status == "COMPLETED")
            .where(tick_log.c.finished_at.is_not(None))
        )
    ]
    rows = conn.execute(
        sa.select(nations.c.id, nations.c.created_at)
    ).all()
    for nation_id, created_at in rows:
        created_utc = _as_utc(created_at)
        turn = max(
            (
                turn_number
                for finished_at, turn_number in completed
                if finished_at <= created_utc
            ),
            default=0,
        )
        conn.execute(
            nations.update()
            .where(nations.c.id == nation_id)
            .values(created_turn=turn)
        )


def upgrade() -> None:
    with op.batch_alter_table("players") as batch_op:
        batch_op.add_column(
            sa.Column(
                "level", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch_op.add_column(
            sa.Column(
                "judge_rating",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_check_constraint(
            "ck_players_level_min", f"level >= {LEVEL_MIN}"
        )
        batch_op.create_check_constraint(
            "ck_players_judge_rating_range",
            f"judge_rating BETWEEN {JUDGE_RATING_MIN} AND {JUDGE_RATING_MAX}",
        )

    with op.batch_alter_table("nations") as batch_op:
        batch_op.add_column(
            sa.Column("created_turn", sa.BigInteger(), nullable=True)
        )

    _backfill_created_turn()

    with op.batch_alter_table("nations") as batch_op:
        batch_op.alter_column(
            "created_turn", existing_type=sa.BigInteger(), nullable=False
        )
        batch_op.create_check_constraint(
            "ck_nations_created_turn_min", "created_turn >= 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_constraint("ck_nations_created_turn_min", type_="check")
        batch_op.drop_column("created_turn")

    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_constraint(
            "ck_players_judge_rating_range", type_="check"
        )
        batch_op.drop_constraint("ck_players_level_min", type_="check")
        batch_op.drop_column("judge_rating")
        batch_op.drop_column("level")
