"""
Module 03_registry data layer: the VK profile cache table (Spec Part
1.1, Appendix B item B2).

Additive only — no existing table is touched:

``registry_vk_profiles`` — the saved VK profile of a player; PK/FK is
``player_id`` -> ``players.id`` ON DELETE CASCADE (the only foreign key
of the module, INV-R1); ``ck_registry_vk_profiles_status`` restricts the
profile FSM to PENDING/OK/UNAVAILABLE; the index
``ix_registry_vk_profiles_next_attempt`` backs the background worker's
"due rows" selection.

Downgrade drops the table and nothing else.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "registry_vk_profiles",
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.String(length=12),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("first_name", sa.String(length=64), nullable=True),
        sa.Column("last_name", sa.String(length=64), nullable=True),
        sa.Column("photo_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "fetched_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="registry_vk_profiles_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "player_id", name="pk_registry_vk_profiles"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','OK','UNAVAILABLE')",
            name="ck_registry_vk_profiles_status",
        ),
    )
    op.create_index(
        "ix_registry_vk_profiles_next_attempt",
        "registry_vk_profiles",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_registry_vk_profiles_next_attempt",
        table_name="registry_vk_profiles",
    )
    op.drop_table("registry_vk_profiles")
