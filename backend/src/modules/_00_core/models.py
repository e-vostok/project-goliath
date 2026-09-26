"""
ORM models for module 00_core.

Defines the 6 core tables: players, nations, provinces, scheduled_actions,
game_clock, and tick_log.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CHAR, CheckConstraint, Enum as SQLEnum, ForeignKey, Index, Integer, JSON, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base

if TYPE_CHECKING:
    from typing import Self


class ScheduledActionStatus(str, enum.Enum):
    """Status of a scheduled action."""
    PENDING = "PENDING"
    APPLIED = "APPLIED"


class TickLogStatus(str, enum.Enum):
    """Status of a tick execution."""
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Player(Base):
    """Represents a player in the game."""
    
    __tablename__ = "players"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vk_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    
    # Relationships
    nations: Mapped[list[Nation]] = relationship(back_populates="owner")


class Nation(Base):
    """Represents a nation (state) in the game."""
    
    __tablename__ = "nations"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_player_id: Mapped[str] = mapped_column(String(36), ForeignKey("players.id"), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    color_hex: Mapped[str] = mapped_column(CHAR(7), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    
    # Relationships
    owner: Mapped[Player] = relationship(back_populates="nations")
    provinces: Mapped[list[Province]] = relationship(back_populates="nation")
    scheduled_actions: Mapped[list[ScheduledAction]] = relationship(back_populates="nation")


class Province(Base):
    """Represents a province on the map."""
    
    __tablename__ = "provinces"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("nations.id"), nullable=True, index=True)
    
    # Relationships
    nation: Mapped[Nation | None] = relationship(back_populates="provinces")


class ScheduledAction(Base):
    """Represents a scheduled game action."""
    
    __tablename__ = "scheduled_actions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    nation_id: Mapped[str] = mapped_column(String(36), ForeignKey("nations.id"), nullable=False, index=True)
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
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(nullable=True)
    
    # Relationships
    nation: Mapped[Nation] = relationship(back_populates="scheduled_actions")
    
    # Composite index for querying pending actions by turn
    __table_args__ = (
        Index("ix_scheduled_actions_turn_status", "turn_number", "status"),
    )


class GameClock(Base):
    """Singleton table tracking the game's current turn and tick schedule."""
    
    __tablename__ = "game_clock"
    
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    current_turn: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_tick_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_tick_at: Mapped[datetime] = mapped_column(nullable=False)
    
    __table_args__ = (
        CheckConstraint("id = 1", name="check_game_clock_singleton"),
    )


class TickLog(Base):
    """Audit log for tick executions."""
    
    __tablename__ = "tick_log"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    turn_number: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[TickLogStatus] = mapped_column(
        SQLEnum(TickLogStatus, native_enum=False),
        nullable=False,
        default=TickLogStatus.RUNNING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
