"""Term exemption arrives (0.14.0 unit 7b).

One additive column on ``orders``:

- ``term_exempt`` — Boolean NOT NULL, default ``false``: the verdict
  term is not enforced for this order — no overdue mark, no refusal,
  no seizure; a verdict is accepted at any time. It is set by the
  seizure itself (the overdue order is taken from its judge and lands
  with an administrator, who gets no bot message about a term) and by
  ``admin_assign_judge`` — a manually assigned judge was never told
  the term and must never be fined for it. The distribution CHECKs
  stay as they are: an exempt order still carries its
  ``distributed_at``/``reminder_at``/``deadline_at`` timestamps, they
  are simply no longer enforced.

The upgrade also grandfathers rows that are ALREADY past their
deadline at the moment of the upgrade — judge set, no verdict,
``deadline_at`` earlier than now: they get ``term_exempt = true``, so
the first worker pass after the deploy does not fine every sitting
judge in bulk for a term that was soft until now. Orders whose term
is still running keep ``term_exempt = false`` and are seized
normally once their own deadline passes.

Downgrade drops the column.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "term_exempt",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
    # Grandfather the already-overdue orders (see the module docstring):
    # judge set, no verdict, deadline earlier than the upgrade moment.
    # The bound ``now`` is typed as timestamptz so the comparison renders
    # exactly like the service's own ``deadline_at < now`` predicates on
    # both dialects.
    op.execute(
        sa.text(
            "UPDATE orders SET term_exempt = :exempt "
            "WHERE judge_player_id IS NOT NULL "
            "AND verdict_at IS NULL "
            "AND deadline_at < :now"
        ).bindparams(
            sa.bindparam("exempt", type_=sa.Boolean(), value=True),
            sa.bindparam(
                "now",
                type_=sa.DateTime(timezone=True),
                value=datetime.now(UTC),
            ),
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("term_exempt")
