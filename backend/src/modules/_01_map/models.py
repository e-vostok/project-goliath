"""
ORM models for module 01_map.

Defines map_ownership_log — the append-only journal of province
ownership changes (Spec Part 1). Entries are written in the same
transaction as the ownership change (INV-M7); the table carries no
UPDATE/DELETE helpers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class MapOwnershipLog(Base):
    """One ownership change of one province on one turn (append-only)."""

    __tablename__ = "map_ownership_log"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    province_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("provinces.id"), nullable=False
    )
    turn_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Logical references only — no FK to nations: a nation row may be
    # deleted while the journal keeps its id/name/color at event time.
    prev_nation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    new_nation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    new_nation_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    new_nation_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(new_nation_id IS NULL AND new_nation_name IS NULL "
            "AND new_nation_color IS NULL) OR "
            "(new_nation_id IS NOT NULL AND new_nation_name IS NOT NULL "
            "AND new_nation_color IS NOT NULL)",
            name="ck_log_new_nation_consistent",
        ),
        Index(
            "ix_map_log_province_turn", "province_id", "turn_number", "id"
        ),
        Index("ix_map_log_turn", "turn_number"),
    )
