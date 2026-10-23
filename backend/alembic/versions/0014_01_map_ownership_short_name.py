"""
Ownership journal gains the new owner's short name (0.10.0 unit 4b).

``map_ownership_log`` already snapshots ``new_nation_id``/
``new_nation_name``/``new_nation_color`` at the event; the map must
show short names, so one more snapshot column rides along:

- ``new_nation_short_name`` — String(100), NULLABLE. NULL on release
  rows, filled on claims — the same pairing rule as the existing
  triple, enforced by the service validator (the named CHECK
  ``ck_log_new_nation_consistent`` is deliberately left unchanged).

Upgrade adds the column and backfills existing claim rows from
``nations`` joined on ``new_nation_id``; a row whose nation no longer
exists falls back to the stored ``new_nation_name``. (The game has 0
journal rows, so in practice nothing is backfilled.)

Downgrade drops the column.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("map_ownership_log") as batch_op:
        batch_op.add_column(
            sa.Column(
                "new_nation_short_name", sa.String(length=100), nullable=True
            )
        )

    # Backfill claim rows from the live nations table; a vanished
    # nation's journal row keeps the best available snapshot — its
    # stored full name.
    op.execute(
        "UPDATE map_ownership_log SET new_nation_short_name = COALESCE("
        "(SELECT short_name FROM nations "
        "WHERE nations.id = map_ownership_log.new_nation_id), "
        "map_ownership_log.new_nation_name) "
        "WHERE new_nation_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("map_ownership_log") as batch_op:
        batch_op.drop_column("new_nation_short_name")
