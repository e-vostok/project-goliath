"""
Three dead columns leave the schema (0.14.0 unit 3a).

``nations.anthem_url`` has been unused since 0.9.0 — the interface
dropped the anthem field and only the column, the DTO key and the
soft link check were carried on the 00_core backlog.
``nation_applications`` loses ``reviewer_player_id`` — together with
its named FK to ``players.id`` — and ``reviewer_assigned_at``: 0.13.0
has no reviewer, any admin decides an application.

``batch_alter_table`` keeps SQLite and PostgreSQL on the same path.
Downgrade re-adds the three columns nullable with the same types and
the same named FK — the dropped values are NOT restored.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_column("anthem_url")

    with op.batch_alter_table("nation_applications") as batch_op:
        batch_op.drop_constraint(
            "fk_nation_applications_reviewer_player_id", type_="foreignkey"
        )
        batch_op.drop_column("reviewer_player_id")
        batch_op.drop_column("reviewer_assigned_at")


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.add_column(
            sa.Column("anthem_url", sa.String(length=2000), nullable=True)
        )

    with op.batch_alter_table("nation_applications") as batch_op:
        batch_op.add_column(
            sa.Column("reviewer_player_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "reviewer_assigned_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_nation_applications_reviewer_player_id",
            "players",
            ["reviewer_player_id"],
            ["id"],
            ondelete="SET NULL",
        )
