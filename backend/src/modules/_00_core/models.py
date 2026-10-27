"""
ORM models for module 00_core.

Defines the 8 core tables: players, nations, provinces, scheduled_actions,
game_clock, tick_log, admin_grants, and admin_audit_log.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base
from modules._00_core.player_stats import (
    JUDGE_RATING_DEFAULT,
    JUDGE_RATING_MAX,
    JUDGE_RATING_MIN,
    LEVEL_DEFAULT,
    LEVEL_MIN,
)

if TYPE_CHECKING:
    pass


class ScheduledActionStatus(enum.StrEnum):
    """Status of a scheduled action."""

    PENDING = "PENDING"
    APPLIED = "APPLIED"


class TickLogStatus(enum.StrEnum):
    """Status of a tick execution."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Player(Base):
    """Represents a player in the game."""

    __tablename__ = "players"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    vk_user_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), nullable=False
    )
    # Scale bounds are pinned by ck_players_level_min /
    # ck_players_judge_rating_range (Spec 03_registry 0/D1, 1.2); the
    # constants live in player_stats.py and no config can widen them.
    level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=LEVEL_DEFAULT, server_default="1"
    )
    judge_rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=JUDGE_RATING_DEFAULT,
        server_default="0",
    )

    # Relationships
    nations: Mapped[list[Nation]] = relationship(back_populates="owner")

    __table_args__ = (
        CheckConstraint(f"level >= {LEVEL_MIN}", name="ck_players_level_min"),
        CheckConstraint(
            f"judge_rating BETWEEN {JUDGE_RATING_MIN} AND {JUDGE_RATING_MAX}",
            name="ck_players_judge_rating_range",
        ),
    )


class Nation(Base):
    """Represents a nation (state) in the game."""

    __tablename__ = "nations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    owner_player_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("players.id"), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    color_hex: Mapped[str] = mapped_column(CHAR(7), nullable=False, unique=True)
    # Descriptive profile fields (Bible §8). NULL only for nations created
    # before the profile migration; NationService.create always writes all
    # three, and they can never be cleared back to NULL (INV-7, INV-8).
    leader_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    leader_title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    history_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Registration 2.0 fields (Spec 1.3, migration 0011). NULL only for
    # nations created before 0.8.0 — NationService.create writes every
    # mandatory field (INV-12) and stores emptied optional fields as NULL.
    # short_name is the exception: NOT NULL and UNIQUE since migration
    # 0012 (0.10.0 unit 4a) — every nation has a short name.
    short_name: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True
    )
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    succession_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    motto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    leader_bio: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # не используется с 0.9.0, снятие — бэклог 00_core
    anthem_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # use_alter + a named FK: nations <-> provinces reference each other
    # (provinces.nation_id already exists), so the capital FK is emitted
    # by a separate ALTER instead of inside CREATE TABLE.
    capital_province_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "provinces.id",
            name="fk_nations_capital_province_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    )
    capital_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # The turn the nation was formed on (INV-R9: immutable after
    # creation). No default: NationService.create stamps the transaction's
    # current_turn; pre-0008 rows were backfilled by the migration.
    created_turn: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Relationships
    owner: Mapped[Player] = relationship(back_populates="nations")
    # Two FK paths link nations<->provinces (nation_id and
    # capital_province_id): pin the ownership join explicitly.
    provinces: Mapped[list[Province]] = relationship(
        back_populates="nation", foreign_keys="Province.nation_id"
    )
    scheduled_actions: Mapped[list[ScheduledAction]] = relationship(
        back_populates="nation"
    )

    __table_args__ = (
        CheckConstraint("created_turn >= 0", name="ck_nations_created_turn_min"),
    )


class Province(Base):
    """Represents a map node: a land province or a sea zone."""

    __tablename__ = "provinces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("nations.id"), nullable=True, index=True
    )
    # LAND — a province a nation can own; SEA — a sea zone, never owned
    # (INV-M4, enforced by ck_provinces_sea_unowned).
    kind: Mapped[str] = mapped_column(
        String(4), nullable=False, default="LAND", server_default="LAND"
    )

    # Relationships
    nation: Mapped[Nation | None] = relationship(
        back_populates="provinces", foreign_keys=[nation_id]
    )

    __table_args__ = (
        CheckConstraint("kind IN ('LAND','SEA')", name="ck_provinces_kind"),
        CheckConstraint(
            "kind = 'LAND' OR nation_id IS NULL",
            name="ck_provinces_sea_unowned",
        ),
    )


class ScheduledAction(Base):
    """Represents a scheduled game action."""

    __tablename__ = "scheduled_actions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    nation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("nations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    module_slug: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    turn_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[ScheduledActionStatus] = mapped_column(
        SQLEnum(ScheduledActionStatus, native_enum=False),
        nullable=False,
        default=ScheduledActionStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    nation: Mapped[Nation | None] = relationship(back_populates="scheduled_actions")

    # Composite index for querying pending actions by turn
    __table_args__ = (
        Index("ix_scheduled_actions_turn_status", "turn_number", "status"),
    )


class GameClock(Base):
    """Singleton table tracking the game's current turn and tick schedule."""

    __tablename__ = "game_clock"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    current_turn: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_tick_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_tick_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (CheckConstraint("id = 1", name="check_game_clock_singleton"),)


class TickLog(Base):
    """Audit log for tick executions."""

    __tablename__ = "tick_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_number: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[TickLogStatus] = mapped_column(
        SQLEnum(TickLogStatus, native_enum=False),
        nullable=False,
        default=TickLogStatus.RUNNING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class AdminGrant(Base):
    """A database-issued admin right (0.11.0 unit 3).

    Complements the ADMIN_VK_USER_IDS env allowlist: require_admin
    accepts a player whose vk_user_id is allowlisted OR who holds a
    grant row here. granted_by_vk_user_id is a plain snapshot of who
    issued the grant — deliberately no FK, so the journal survives
    player deletion.
    """

    __tablename__ = "admin_grants"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    player_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("players.id"), nullable=False, unique=True
    )
    granted_by_vk_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminAuditLog(Base):
    """Bounded journal of admin-panel actions (0.11.0 unit 3).

    Keeps only the newest admin_panel.audit_log_max_rows rows:
    AdminAuditService.record() deletes the oldest ones above the cap
    automatically — nobody deletes or edits rows by hand.

    actor_vk_user_id is a snapshot, not a FK: the history must survive
    deletion of the acting player. details carries ids and before/after
    values only — never tokens or raw launch params.
    """

    __tablename__ = "admin_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_vk_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
