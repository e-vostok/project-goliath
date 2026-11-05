"""
Judge refusal arrives (0.14.0 unit 7a).

Two additive columns on ``orders``:

- ``refused_judge_ids`` — JSON NOT NULL, default ``[]``: the plain
  player-id strings of every judge who refused this order, kept so the
  automatic selector never offers them the order again. Deliberately
  no foreign key — a logical list, not a relational link; a deleted
  player simply stays listed.
- ``assignment_no`` — Integer NOT NULL, default 1, named CHECK
  ``ck_orders_assignment_no_positive`` (``assignment_no >= 1``): the
  1-based number of the current judge assignment. A refusal increments
  it; the judge-facing bot event keys carry it from the second
  assignment on, so the first judge's dedupe key never swallows the
  next judge's assignment and reminder rows.

Existing rows were assigned exactly once and never refused — both
defaults describe them exactly. Downgrade drops the CHECK and both
columns.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "refused_judge_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )
        batch_op.add_column(
            sa.Column(
                "assignment_no",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_check_constraint(
            "ck_orders_assignment_no_positive", "assignment_no >= 1"
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint(
            "ck_orders_assignment_no_positive", type_="check"
        )
        batch_op.drop_column("assignment_no")
        batch_op.drop_column("refused_judge_ids")
