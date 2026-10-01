"""
Nation profile fields: leader_name, leader_title, history_url.

Spec 1.1 adds descriptive nation profile fields (Bible §8). All three
columns are nullable so the nations that already exist at upgrade time
keep working unchanged (legacy rows with NULLs); NationService.create
writes all three values for every nation created after this migration,
and they can never be cleared back to NULL (INV-7, INV-8). No unique
constraints or indexes — the fields are descriptive only (INV-10).

Column lengths match the config schema's `le` upper bounds
(leader_name/leader_title 100, history_url 2000), so any configuration
the schema accepts still fits the columns without a new migration.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.add_column(
            sa.Column("leader_name", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("leader_title", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("history_url", sa.String(length=2000), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_column("history_url")
        batch_op.drop_column("leader_title")
        batch_op.drop_column("leader_name")
