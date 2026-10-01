"""
Let scheduled actions outlive their nation: ON DELETE SET NULL.

Migration 0003 created scheduled_actions.nation_id as NOT NULL with a
plain (RESTRICT) foreign key, so deleting a nation that still has
scheduled action rows raised an integrity error. The column becomes
nullable and the constraint gains ondelete="SET NULL": a deleted nation
leaves its action rows behind as orphaned historical records — the same
INV-6 policy provinces already follow.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_FK_NAME = "scheduled_actions_nation_id_fkey"


def upgrade() -> None:
    with op.batch_alter_table("scheduled_actions") as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.alter_column(
            "nation_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.create_foreign_key(
            _FK_NAME,
            "nations",
            ["nation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_actions") as batch_op:
        batch_op.drop_constraint(_FK_NAME, type_="foreignkey")
        batch_op.alter_column(
            "nation_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.create_foreign_key(
            _FK_NAME,
            "nations",
            ["nation_id"],
            ["id"],
        )
