"""
Module 02_bot data layer: the four bot tables (Spec 02_bot Part 1.1,
Appendix B item B5).

Additive only — no existing table is touched:

1. ``bot_consents`` — the player's consent state for community
   messages; PK/FK is ``player_id`` -> ``players.id`` ON DELETE
   CASCADE; ``ck_bot_consents_state`` restricts the FSM to
   UNKNOWN/ALLOWED/DENIED.
2. ``bot_outbox`` — the outgoing message queue; BIGINT PK
   (INTEGER variant on SQLite so autoincrement works, the
   tick_log.id lesson from migration 0002 / map_ownership_log from
   0006), FK ``player_id`` -> ``players.id`` ON DELETE CASCADE,
   named CHECKs ``ck_bot_outbox_kind`` / ``ck_bot_outbox_priority`` /
   ``ck_bot_outbox_status``, ``uq_bot_outbox_dedup`` on
   (player_id, type_key, event_key) and the two readiness indexes
   ``ix_bot_outbox_ready`` / ``ix_bot_outbox_player_status``.
3. ``bot_vk_events`` — the inbound Callback API journal;
   ``event_id`` UNIQUE makes re-delivery idempotent;
   ``vk_user_id`` is a logical (FK-less) reference to
   ``players.vk_user_id``.
4. ``bot_state`` — the module singleton (``ck_bot_state_singleton``
   pins ``id = 1``); the seed row ``(id=1, last_digest_turn=0)`` is
   inserted here.

Downgrade drops the four tables and nothing else.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_consents",
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column(
            "state",
            sa.String(length=8),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column("state_source", sa.String(length=24), nullable=False),
        sa.Column(
            "state_changed_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "last_checked_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "last_plate_at", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="bot_consents_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("player_id", name="pk_bot_consents"),
        sa.CheckConstraint(
            "state IN ('UNKNOWN','ALLOWED','DENIED')",
            name="ck_bot_consents_state",
        ),
    )

    op.create_table(
        "bot_outbox",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("type_key", sa.String(length=40), nullable=False),
        sa.Column("event_key", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("counts_toward_cap", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=8),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("drop_reason", sa.String(length=24), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "not_before", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "expires_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_attempt_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.Column(
            "lease_until", sa.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("group_id", sa.String(length=36), nullable=True),
        sa.Column("random_id", sa.Integer(), nullable=True),
        sa.Column("render_mode", sa.String(length=8), nullable=True),
        sa.Column("vk_message_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name="bot_outbox_player_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bot_outbox"),
        sa.CheckConstraint(
            "kind IN ('NOTIFICATION','REPLY')", name="ck_bot_outbox_kind"
        ),
        sa.CheckConstraint(
            "priority IN ('critical','normal')",
            name="ck_bot_outbox_priority",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','LEASED','SENT','EXPIRED','DROPPED','FAILED')",
            name="ck_bot_outbox_status",
        ),
        sa.UniqueConstraint(
            "player_id", "type_key", "event_key", name="uq_bot_outbox_dedup"
        ),
    )
    op.create_index(
        "ix_bot_outbox_ready",
        "bot_outbox",
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_bot_outbox_player_status",
        "bot_outbox",
        ["player_id", "status", "sent_at"],
        unique=False,
    )

    op.create_table(
        "bot_vk_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "received_at", sa.TIMESTAMP(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bot_vk_events"),
        sa.UniqueConstraint("event_id", name="uq_bot_vk_events_event_id"),
    )

    op.create_table(
        "bot_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "last_digest_turn",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bot_state"),
        sa.CheckConstraint("id = 1", name="ck_bot_state_singleton"),
    )

    # Seed the module singleton (Spec 1.1): one row, id=1, no digests
    # produced yet. A plain table construct (not the ORM model) keeps
    # the migration valid even if the model gains columns later.
    bot_state = sa.table(
        "bot_state",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("last_digest_turn", sa.Integer(), nullable=False),
    )
    op.execute(
        bot_state.insert().values(id=1, last_digest_turn=0)
    )


def downgrade() -> None:
    op.drop_index("ix_bot_outbox_player_status", table_name="bot_outbox")
    op.drop_index("ix_bot_outbox_ready", table_name="bot_outbox")
    op.drop_table("bot_state")
    op.drop_table("bot_vk_events")
    op.drop_table("bot_outbox")
    op.drop_table("bot_consents")
