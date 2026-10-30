"""
The uploaded nation pictures get their table (0.12.0 unit 5b).

``nation_images`` stores the player-uploaded flag and portrait: one row
per (nation_id, kind), both WebP variants as BYTEA next to the sha256
content key that names their public URL. The catalogue columns went
away in 0017; until this table exists nations can show only the
client-side placeholders.

- ``UNIQUE (nation_id, kind)`` enforces INV-15 (at most one picture of
  each kind per nation); a replacement upload rewrites the row.
- ``CHECK (kind IN ('flag', 'portrait'))`` pins the two kinds.
- ``nation_id -> nations.id ON DELETE CASCADE`` is only a safety net —
  the service and the world reset delete rows explicitly first
  (INV-19); ``uploaded_by_player_id -> players.id ON DELETE SET NULL``
  keeps the row when the uploader's account is deleted.
- A non-unique index on ``sha256`` serves GET /images/{sha256}/… —
  two nations with the same file legitimately share the hash.

Additive: no other table is touched. There are no test nations on the
production server, nothing is backfilled and no data is migrated.
Downgrade simply drops the table.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "nation_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nation_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("full_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("thumb_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_player_id", sa.String(length=36), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flag', 'portrait')", name="ck_nation_images_kind"
        ),
        sa.ForeignKeyConstraint(
            ["nation_id"],
            ["nations.id"],
            name="fk_nation_images_nation_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_player_id"],
            ["players.id"],
            name="fk_nation_images_uploaded_by_player_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nation_images"),
        sa.UniqueConstraint(
            "nation_id", "kind", name="uq_nation_images_nation_kind"
        ),
    )
    op.create_index(
        "ix_nation_images_sha256", "nation_images", ["sha256"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_nation_images_sha256", table_name="nation_images")
    op.drop_table("nation_images")
