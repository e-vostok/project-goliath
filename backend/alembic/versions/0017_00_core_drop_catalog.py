"""
The ready-made flag/portrait catalog goes away (0.12.0 unit 4a).

Until the upload pipeline lands (units 5–6) nations carry no picture at
all: the catalog is gone for good — config section, catalog ids,
endpoint lists and the placeholder files — so the columns that stored
the picks are dropped:

- ``nations.flag_id`` — String(50), NULLABLE;
- ``nations.portrait_id`` — String(50), NULLABLE;
- ``orders.nation_flag_id`` — String(50), NULLABLE.

A ``00_core`` revision touches the ``orders`` table on purpose: Spec
00_core Part 1 sanctions it — ``nation_flag_id`` is a snapshot copy of
the dropped ``nations.flag_id`` taken at submission (INV-O6); nothing
else of ``04_orders`` is touched. No other table is touched either.

There are no test nations and no orders on the production server
(confirmed by the Project Owner 27.10.2026), so nothing is backfilled
and no data is migrated. ``batch_alter_table`` keeps SQLite and
PostgreSQL on the same path.

Downgrade adds the same three columns back as nullable — the schema
returns, the dropped ids do not (they are not restored).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_column("flag_id")
        batch_op.drop_column("portrait_id")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("nation_flag_id")


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.add_column(
            sa.Column("flag_id", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("portrait_id", sa.String(length=50), nullable=True)
        )

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column("nation_flag_id", sa.String(length=50), nullable=True)
        )
