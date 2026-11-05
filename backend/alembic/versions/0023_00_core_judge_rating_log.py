"""
The judge-rating journal arrives (0.14.0 unit 6a).

``judge_rating_log`` is the append-only record of every change to
``players.judge_rating``: each row stores the requested ``delta``, the
``applied_delta`` after the scale clamp, the rating before and after,
a machine ``reason_code`` (the order-refusal and overdue penalties plus
``MANUAL`` for the admin-panel edit), the free-text ``note`` a MANUAL
row must carry, and the ``source_key`` that makes the operation
idempotent — a repeated event can never move the rating twice.

- ``player_id -> players.id ON DELETE CASCADE``: the journal dies with
  the rated player.
- ``actor_player_id -> players.id ON DELETE SET NULL``: the admin who
  made a MANUAL change may leave the game; the entry survives.
- ``UNIQUE (source_key)`` is the idempotency key the service checks
  under the player's row lock.
- ``CHECK`` pins the four reason codes; ``Index(player_id, id)`` serves
  the newest-first listing the panel paginates by id.

The world reset keeps players (accounts survive), so it neither wipes
this journal nor touches the ratings — the two never disagree. Nothing
is backfilled: the rating never had a write path before, so no change
history exists. Downgrade drops the table.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "judge_rating_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("applied_delta", sa.Integer(), nullable=False),
        sa.Column("rating_before", sa.Integer(), nullable=False),
        sa.Column("rating_after", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=24), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("actor_player_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "reason_code IN ('ORDER_REFUSED', 'ORDER_REFUSED_LATE', "
            "'ORDER_OVERDUE', 'MANUAL')",
            name="ck_judge_rating_log_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="fk_judge_rating_log_player_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_player_id"],
            ["players.id"],
            name="fk_judge_rating_log_actor_player_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_judge_rating_log"),
        sa.UniqueConstraint("source_key", name="uq_judge_rating_log_source_key"),
    )
    op.create_index(
        "ix_judge_rating_log_player_id",
        "judge_rating_log",
        ["player_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_judge_rating_log_player_id", table_name="judge_rating_log"
    )
    op.drop_table("judge_rating_log")
