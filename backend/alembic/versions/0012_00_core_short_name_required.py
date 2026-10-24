"""
Short name becomes mandatory (0.10.0 unit 4a).

``nations.short_name`` goes NOT NULL while keeping the named UNIQUE
constraint from 0011. Rows that predate the rule inherit the full
``name`` as their short name first — ``UPDATE ... WHERE short_name IS
NULL`` runs against the live ``uq_nations_short_name`` constraint, so
a collision with an existing short name aborts the migration loudly
instead of silently rewriting data. (There are 0 nations in the game,
so in practice nothing is backfilled.)

Done via ``batch_alter_table`` so SQLite and PostgreSQL take the same
path. Downgrade makes the column nullable again; the data it backfilled
is left as-is.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Backfill before the NOT NULL: a NULL short_name takes the full
    # name. If that collides with an existing short_name the UNIQUE
    # constraint raises and the migration fails loudly — by design.
    op.execute(
        "UPDATE nations SET short_name = name WHERE short_name IS NULL"
    )
    with op.batch_alter_table("nations") as batch_op:
        batch_op.alter_column(
            "short_name",
            existing_type=sa.String(length=100),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.alter_column(
            "short_name",
            existing_type=sa.String(length=100),
            nullable=True,
        )
