"""
Module 04_orders data layer: the ``orders`` table (Spec Part 1,
Appendix B item B6).

Additive only — no existing table is touched:

``orders`` — one row per submitted order; the verdict is a column group
of the same row (D1) and the stage is derived from column fill (D4),
pinned by eight named CHECKs (INV-O2). ``uq_orders_number`` is the
public order number (D2); ``uq_orders_author_client_request`` is the
idempotent-submission key (INV-O9). Foreign keys go only to
``players.id`` (INV-O7); ``nation_*`` is a snapshot without an FK
(INV-O6). Three partial indexes back the judge workload, the
distribution queue and the reminder sweep — declared for both
PostgreSQL and SQLite.

Downgrade drops the table and nothing else.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("author_player_id", sa.String(length=36), nullable=False),
        sa.Column("client_request_id", sa.String(length=36), nullable=False),
        sa.Column("nation_id", sa.String(length=36), nullable=False),
        sa.Column("nation_name", sa.String(length=100), nullable=False),
        sa.Column("nation_color", sa.CHAR(length=7), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("article_url", sa.String(length=2000), nullable=False),
        sa.Column(
            "submitted_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column("judge_player_id", sa.String(length=36), nullable=True),
        sa.Column(
            "distributed_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("deadline_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reminder_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "reminder_sent_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("verdict_title", sa.String(length=200), nullable=True),
        sa.Column("verdict_summary", sa.String(length=2000), nullable=True),
        sa.Column("verdict_url", sa.String(length=2000), nullable=True),
        sa.Column("verdict_effects", sa.JSON(), nullable=True),
        sa.Column("verdict_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_player_id"],
            ["players.id"],
            name="orders_author_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_player_id"],
            ["players.id"],
            name="orders_judge_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_orders"),
        sa.UniqueConstraint("number", name="uq_orders_number"),
        sa.UniqueConstraint(
            "author_player_id",
            "client_request_id",
            name="uq_orders_author_client_request",
        ),
        sa.CheckConstraint(
            "number >= 1", name="ck_orders_number_positive"
        ),
        sa.CheckConstraint(
            "judge_player_id IS NULL "
            "OR judge_player_id <> author_player_id",
            name="ck_orders_judge_not_author",
        ),
        sa.CheckConstraint(
            "(judge_player_id IS NULL AND distributed_at IS NULL "
            "AND deadline_at IS NULL AND reminder_at IS NULL) OR "
            "(judge_player_id IS NOT NULL AND distributed_at IS NOT NULL "
            "AND deadline_at IS NOT NULL AND reminder_at IS NOT NULL)",
            name="ck_orders_distribution_all_or_none",
        ),
        sa.CheckConstraint(
            "deadline_at IS NULL OR "
            "(distributed_at < reminder_at AND reminder_at < deadline_at)",
            name="ck_orders_distribution_order",
        ),
        sa.CheckConstraint(
            "(verdict_title IS NULL AND verdict_summary IS NULL "
            "AND verdict_url IS NULL AND verdict_at IS NULL) OR "
            "(verdict_title IS NOT NULL AND verdict_summary IS NOT NULL "
            "AND verdict_url IS NOT NULL AND verdict_at IS NOT NULL)",
            name="ck_orders_verdict_all_or_none",
        ),
        sa.CheckConstraint(
            "verdict_at IS NULL OR judge_player_id IS NOT NULL",
            name="ck_orders_verdict_needs_judge",
        ),
        sa.CheckConstraint(
            "verdict_at IS NULL OR verdict_at >= distributed_at",
            name="ck_orders_verdict_after_distribution",
        ),
        sa.CheckConstraint(
            "reminder_sent_at IS NULL OR judge_player_id IS NOT NULL",
            name="ck_orders_reminder_needs_judge",
        ),
    )
    op.create_index(
        "ix_orders_author_player_id",
        "orders",
        ["author_player_id"],
        unique=False,
    )
    op.create_index(
        "ix_orders_judge_player_id",
        "orders",
        ["judge_player_id"],
        unique=False,
    )
    op.create_index(
        "ix_orders_pending_by_judge",
        "orders",
        ["judge_player_id"],
        unique=False,
        postgresql_where=sa.text("verdict_at IS NULL"),
        sqlite_where=sa.text("verdict_at IS NULL"),
    )
    op.create_index(
        "ix_orders_unassigned",
        "orders",
        ["submitted_at"],
        unique=False,
        postgresql_where=sa.text("judge_player_id IS NULL"),
        sqlite_where=sa.text("judge_player_id IS NULL"),
    )
    op.create_index(
        "ix_orders_reminders_due",
        "orders",
        ["reminder_at"],
        unique=False,
        postgresql_where=sa.text(
            "reminder_sent_at IS NULL AND verdict_at IS NULL"
        ),
        sqlite_where=sa.text(
            "reminder_sent_at IS NULL AND verdict_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orders_reminders_due", table_name="orders"
    )
    op.drop_index(
        "ix_orders_unassigned", table_name="orders"
    )
    op.drop_index(
        "ix_orders_pending_by_judge", table_name="orders"
    )
    op.drop_index(
        "ix_orders_judge_player_id", table_name="orders"
    )
    op.drop_index(
        "ix_orders_author_player_id", table_name="orders"
    )
    op.drop_table("orders")
