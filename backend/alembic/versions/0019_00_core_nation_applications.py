"""
The nation applications («анкеты») arrive (0.13.0 unit 4).

``nation_applications`` keeps one row per registration application —
at most one LIVE (DRAFT/PENDING) row per player, pinned by the partial
unique index on ``owner_player_id``; three more partial unique indexes
make a PENDING row reserve its ``name``, ``short_name`` and
``color_hex`` (APP-1). ``nation_application_provinces`` stores the
picked provinces in pick order; the partial unique index on
``province_id WHERE is_reserved`` keeps a province reservable by a
single application — the flag is true exactly while the row's
application sits in PENDING.

``nation_images`` learns to serve applications too: ``nation_id``
becomes nullable, ``application_id`` arrives with the same CASCADE
shape, ``ck_nation_images_one_owner`` demands exactly one owner and
``uq_nation_images_application_kind`` repeats the (owner, kind) rule
of INV-15 — picture rows flip to the nation at acceptance (unit 5).

The game has no live applications and no image rows on production yet,
so nothing is backfilled. ``batch_alter_table`` keeps SQLite and
PostgreSQL on the same path for the ``nation_images`` reshape.

Downgrade restores the exact 0018 shape: application-owned image rows
are deleted first (they cannot survive ``nation_id`` going back to
NOT NULL), the new column, constraint and unique key are dropped, and
both application tables are dropped.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_LIVE = sa.text("status IN ('DRAFT', 'PENDING')")
_PENDING = sa.text("status = 'PENDING'")
_RESERVED = sa.text("is_reserved")


def upgrade() -> None:
    op.create_table(
        "nation_applications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_player_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("short_name", sa.String(length=100), nullable=False),
        sa.Column("color_hex", sa.CHAR(length=7), nullable=False),
        sa.Column("motto", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("leader_name", sa.String(length=100), nullable=True),
        sa.Column("leader_title", sa.String(length=100), nullable=True),
        sa.Column("gender", sa.String(length=10), nullable=True),
        sa.Column("succession_type", sa.String(length=20), nullable=True),
        sa.Column("leader_bio", sa.String(length=2000), nullable=True),
        sa.Column("history_url", sa.String(length=2000), nullable=True),
        sa.Column("capital_province_id", sa.Integer(), nullable=True),
        sa.Column("capital_name", sa.String(length=100), nullable=True),
        sa.Column("draft_reason", sa.String(length=10), nullable=True),
        sa.Column("return_comment", sa.String(length=300), nullable=True),
        sa.Column("submissions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_player_id", sa.String(length=36), nullable=True),
        sa.Column(
            "reviewer_assigned_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_player_id", sa.String(length=36), nullable=True),
        sa.Column("auto_accepted", sa.Boolean(), nullable=True),
        sa.Column("accepted_nation_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING', 'ACCEPTED')",
            name="ck_nation_applications_status",
        ),
        sa.CheckConstraint(
            "draft_reason IS NULL OR "
            "draft_reason IN ('returned', 'cancelled', 'failed')",
            name="ck_nation_applications_draft_reason",
        ),
        sa.ForeignKeyConstraint(
            ["owner_player_id"],
            ["players.id"],
            name="fk_nation_applications_owner_player_id",
        ),
        sa.ForeignKeyConstraint(
            ["capital_province_id"],
            ["provinces.id"],
            name="fk_nation_applications_capital_province_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_player_id"],
            ["players.id"],
            name="fk_nation_applications_reviewer_player_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_nation_id"],
            ["nations.id"],
            name="fk_nation_applications_accepted_nation_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nation_applications"),
    )
    op.create_index(
        "uq_nation_applications_owner_live",
        "nation_applications",
        ["owner_player_id"],
        unique=True,
        sqlite_where=_LIVE,
        postgresql_where=_LIVE,
    )
    op.create_index(
        "uq_nation_applications_pending_name",
        "nation_applications",
        ["name"],
        unique=True,
        sqlite_where=_PENDING,
        postgresql_where=_PENDING,
    )
    op.create_index(
        "uq_nation_applications_pending_short_name",
        "nation_applications",
        ["short_name"],
        unique=True,
        sqlite_where=_PENDING,
        postgresql_where=_PENDING,
    )
    op.create_index(
        "uq_nation_applications_pending_color_hex",
        "nation_applications",
        ["color_hex"],
        unique=True,
        sqlite_where=_PENDING,
        postgresql_where=_PENDING,
    )

    op.create_table(
        "nation_application_provinces",
        sa.Column("application_id", sa.String(length=36), nullable=False),
        sa.Column("province_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "is_reserved", sa.Boolean(), server_default="0", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["nation_applications.id"],
            name="fk_nation_application_provinces_application_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["province_id"],
            ["provinces.id"],
            name="fk_nation_application_provinces_province_id",
        ),
        sa.PrimaryKeyConstraint(
            "application_id", "province_id", name="pk_nation_application_provinces"
        ),
    )
    op.create_index(
        "uq_nation_application_provinces_reserved",
        "nation_application_provinces",
        ["province_id"],
        unique=True,
        sqlite_where=_RESERVED,
        postgresql_where=_RESERVED,
    )

    with op.batch_alter_table("nation_images") as batch_op:
        batch_op.alter_column(
            "nation_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("application_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_nation_images_application_id",
            "nation_applications",
            ["application_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_nation_images_application_kind", ["application_id", "kind"]
        )
        batch_op.create_check_constraint(
            "ck_nation_images_one_owner",
            "(nation_id IS NULL) <> (application_id IS NULL)",
        )


def downgrade() -> None:
    # Application-owned image rows cannot survive nation_id going back
    # to NOT NULL — remove them before the reshape.
    op.execute("DELETE FROM nation_images WHERE nation_id IS NULL")
    with op.batch_alter_table("nation_images") as batch_op:
        batch_op.drop_constraint("ck_nation_images_one_owner", type_="check")
        batch_op.drop_constraint(
            "uq_nation_images_application_kind", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_nation_images_application_id", type_="foreignkey"
        )
        batch_op.drop_column("application_id")
        batch_op.alter_column(
            "nation_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )

    op.drop_index(
        "uq_nation_application_provinces_reserved",
        table_name="nation_application_provinces",
    )
    op.drop_table("nation_application_provinces")
    op.drop_index(
        "uq_nation_applications_pending_color_hex",
        table_name="nation_applications",
    )
    op.drop_index(
        "uq_nation_applications_pending_short_name",
        table_name="nation_applications",
    )
    op.drop_index(
        "uq_nation_applications_pending_name", table_name="nation_applications"
    )
    op.drop_index(
        "uq_nation_applications_owner_live", table_name="nation_applications"
    )
    op.drop_table("nation_applications")
