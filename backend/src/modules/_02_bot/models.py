"""
ORM models for module 02_bot.

Defines the four tables of Spec Part 1.1:

- ``bot_consents`` — the player's consent state for community messages;
- ``bot_outbox`` — the outgoing message queue (one row = one event);
- ``bot_vk_events`` — the inbound Callback API journal;
- ``bot_state`` — the module singleton (one row, ``id = 1``).

Data layer only: no business logic and no config access — balance lives
in ``configs/02_bot.yaml`` behind ``config_schema.py``. Foreign keys
point exclusively at ``players.id`` (INV-B11).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class BotConsent(Base):
    """A player's consent state for messages from the community."""

    __tablename__ = "bot_consents"

    player_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(
        String(8), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    state_source: Mapped[str] = mapped_column(String(24), nullable=False)
    state_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_plate_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('UNKNOWN','ALLOWED','DENIED')",
            name="ck_bot_consents_state",
        ),
    )


class BotOutbox(Base):
    """One queued outgoing message event (Spec Part 1.1)."""

    __tablename__ = "bot_outbox"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    player_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    type_key: Mapped[str] = mapped_column(String(40), nullable=False)
    event_key: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    counts_toward_cap: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="PENDING", server_default="PENDING"
    )
    drop_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    not_before: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    random_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vk_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('NOTIFICATION','REPLY')", name="ck_bot_outbox_kind"
        ),
        CheckConstraint(
            "priority IN ('critical','normal')",
            name="ck_bot_outbox_priority",
        ),
        CheckConstraint(
            "status IN ('PENDING','LEASED','SENT','EXPIRED','DROPPED','FAILED')",
            name="ck_bot_outbox_status",
        ),
        UniqueConstraint(
            "player_id", "type_key", "event_key", name="uq_bot_outbox_dedup"
        ),
        Index("ix_bot_outbox_ready", "status", "next_attempt_at"),
        Index(
            "ix_bot_outbox_player_status", "player_id", "status", "sent_at"
        ),
    )


class BotVkEvent(Base):
    """One inbound Callback API event (idempotent by event_id)."""

    __tablename__ = "bot_vk_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Logical link to players.vk_user_id only — deliberately no FK
    # (INV-B11): an event may arrive before the player row exists.
    vk_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("event_id", name="uq_bot_vk_events_event_id"),
    )


class BotState(Base):
    """Module singleton: one row, id = 1 (last processed digest turn)."""

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_digest_turn: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_bot_state_singleton"),
    )
