"""
Registration 2.0: eleven descriptive nation columns (Spec 1.3 Part 1).

Adds the symbolics/leadership/links/capital fields to ``nations`` —
``short_name`` (UNIQUE, INV-11), ``gender``, ``succession_type``,
``motto``, ``description``, ``leader_bio``, ``flag_id``,
``portrait_id``, ``anthem_url``, ``capital_province_id`` and
``capital_name``. All columns are nullable so nations that already
exist at upgrade time keep working unchanged (legacy rows with NULLs);
``NationService.create`` writes every mandatory field for nations
created after this migration (INV-12).

Column lengths match the config schema's ``le`` upper bounds, so any
configuration the schema accepts still fits without a new migration.
``capital_province_id`` creates the nations <-> provinces reference
cycle with ``provinces.nation_id``: the named FK
``fk_nations_capital_province_id`` carries ON DELETE SET NULL and the
model side declares ``use_alter=True``.

Done via ``batch_alter_table`` so SQLite and PostgreSQL take the same
path. Existing data is not touched. Downgrade drops the FK and the
eleven columns.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

_CAPITAL_FK = "fk_nations_capital_province_id"

_NEW_COLUMNS = [
    "short_name",
    "gender",
    "succession_type",
    "motto",
    "description",
    "leader_bio",
    "flag_id",
    "portrait_id",
    "anthem_url",
    "capital_province_id",
    "capital_name",
]


def upgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.add_column(
            sa.Column("short_name", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("gender", sa.String(length=10), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "succession_type", sa.String(length=20), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column("motto", sa.String(length=100), nullable=True)
        )
        batch_op.add_column(
            sa.Column("description", sa.String(length=200), nullable=True)
        )
        batch_op.add_column(
            sa.Column("leader_bio", sa.String(length=2000), nullable=True)
        )
        batch_op.add_column(
            sa.Column("flag_id", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("portrait_id", sa.String(length=50), nullable=True)
        )
        batch_op.add_column(
            sa.Column("anthem_url", sa.String(length=2000), nullable=True)
        )
        batch_op.add_column(
            sa.Column("capital_province_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("capital_name", sa.String(length=100), nullable=True)
        )
        # The UNIQUE must be emitted explicitly: inside batch
        # add_column, ``unique=True`` on the Column is not guaranteed to
        # survive ALTER TABLE ADD COLUMN on PostgreSQL.
        batch_op.create_unique_constraint(
            "uq_nations_short_name", ["short_name"]
        )
        batch_op.create_foreign_key(
            _CAPITAL_FK,
            "provinces",
            ["capital_province_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("nations") as batch_op:
        batch_op.drop_constraint(_CAPITAL_FK, type_="foreignkey")
        for column in _NEW_COLUMNS:
            batch_op.drop_column(column)
