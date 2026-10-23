"""
Order nation snapshot gains short name and flag id (0.10.0 unit 4b).

``orders`` already stores the immutable ``nation_id``/``nation_name``/
``nation_color`` snapshot taken at submission (INV-O6); the Registry
«Приказы» table must show the short name and the flag, so two more
snapshot columns ride along:

- ``nation_short_name`` — String(100), NOT NULL;
- ``nation_flag_id`` — String(50), NULLABLE (the type of
  ``nations.flag_id``; NULL for nations without a chosen flag).

Upgrade adds both columns nullable, backfills them from ``nations``
joined on ``orders.nation_id`` — a row whose nation no longer exists
falls back to the stored full name — and then sets ``nation_short_name``
NOT NULL. ``batch_alter_table`` keeps SQLite and PostgreSQL on the same
path. (The game has 0 orders, so in practice nothing is backfilled.)

Downgrade drops both columns.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column("nation_short_name", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("nation_flag_id", sa.String(length=50), nullable=True)
        )

    # Backfill from the live nations table; a vanished nation's order
    # keeps the best available snapshot — its stored full name.
    op.execute(
        "UPDATE orders SET nation_short_name = COALESCE("
        "(SELECT short_name FROM nations WHERE nations.id = orders.nation_id), "
        "orders.nation_name)"
    )
    op.execute(
        "UPDATE orders SET nation_flag_id = "
        "(SELECT flag_id FROM nations WHERE nations.id = orders.nation_id) "
        "WHERE EXISTS "
        "(SELECT 1 FROM nations WHERE nations.id = orders.nation_id)"
    )

    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "nation_short_name",
            existing_type=sa.String(length=100),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("nation_flag_id")
        batch_op.drop_column("nation_short_name")
