"""
Admin grants and the admin audit log (0.11.0 unit 3).

Two new 00_core tables:

- ``admin_grants`` — database-issued admin rights, complementing the
  ADMIN_VK_USER_IDS env allowlist. One row per player
  (``player_id`` UNIQUE, FK -> players.id); ``granted_by_vk_user_id``
  is a plain snapshot of the granting admin — deliberately no FK, so
  the record survives deletion of the granting player.
- ``admin_audit_log`` — bounded journal of admin-panel actions:
  only the newest ``admin_panel.audit_log_max_rows`` rows are kept,
  AdminAuditService.record() deletes the oldest ones automatically.
  ``actor_vk_user_id`` is a snapshot too (no FK): history survives
  player deletion. ``details`` is JSON for ids and before/after
  values only — never tokens or raw launch params.

Neither table is touched by the world reset: the audit log is
durable history (bounded by the row cap), and grants define who may
operate the panel.

Downgrade drops both tables.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "player_id",
            sa.String(36),
            sa.ForeignKey("players.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("granted_by_vk_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True, primary_key=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor_vk_user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index(
        op.f("ix_admin_audit_log_created_at"),
        "admin_audit_log",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_admin_audit_log_actor_vk_user_id"),
        "admin_audit_log",
        ["actor_vk_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_audit_log_actor_vk_user_id"), table_name="admin_audit_log"
    )
    op.drop_index(
        op.f("ix_admin_audit_log_created_at"), table_name="admin_audit_log"
    )
    op.drop_table("admin_audit_log")
    op.drop_table("admin_grants")
