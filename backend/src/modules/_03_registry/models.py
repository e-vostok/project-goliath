"""
ORM models for module 03_registry.

Defines the module's tables of Spec Part 1.1 and 0.11.0 unit 11:

- ``registry_vk_profiles`` — the saved VK profile of a player (name,
  small avatar, fetch bookkeeping for the background profile worker).
- ``registry_player_numbers`` — the permanent public Registry number
  of a player: issued once by ``service.ensure_player_numbers``,
  never changed and never reused after the player is gone.
- ``registry_number_counter`` — the single counter row the issuing
  draws the next number from; it only grows, so a freed number stays
  a gap forever.

Data layer only: no business logic and no config access — balance and
the table descriptions live in ``configs/03_registry.yaml`` behind
``config_schema.py``. The only foreign keys point at ``players.id``
(INV-R1; the module never writes other modules' tables).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class RegistryVkProfile(Base):
    """The cached VK profile of one player (FSM — Spec 2.3)."""

    __tablename__ = "registry_vk_profiles"

    player_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="PENDING", server_default="PENDING"
    )
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','OK','UNAVAILABLE')",
            name="ck_registry_vk_profiles_status",
        ),
        Index("ix_registry_vk_profiles_next_attempt", "next_attempt_at"),
    )


class RegistryPlayerNumber(Base):
    """The permanent public Registry number of one player (0.11.0 unit 11).

    Written once, never updated: the number outlives the player — the
    delete hook removes the row, the freed ``number`` is never reissued
    (the counter only grows). ``uq_registry_player_numbers_number`` is
    the second line of defence against a duplicate.
    """

    __tablename__ = "registry_player_numbers"

    player_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("number", name="uq_registry_player_numbers_number"),
    )


class RegistryNumberCounter(Base):
    """The single ``last_number`` row the issuing draws from (0.11.0 unit 11).

    Always exactly one row with ``id = 1`` (migration 0016 seeds it
    with the player count, ``ensure_player_numbers`` creates it on
    schemas built from metadata alone). Never reset and never deleted:
    issued numbers stay reserved even when their players are gone.
    """

    __tablename__ = "registry_number_counter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_registry_number_counter_singleton"),
    )
