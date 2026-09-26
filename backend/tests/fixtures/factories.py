"""
Polyfactory factories for 00_core models.

Provides test data factories for Player, Nation, and Province models.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory

from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
    TickLog,
    TickLogStatus,
)


def utcnow():
    """Helper to get current UTC datetime."""
    return datetime.now(timezone.utc)


class PlayerFactory(SQLAlchemyFactory[Player]):
    """Factory for creating Player instances."""
    
    __model__ = Player
    
    id = lambda: str(uuid.uuid4())
    vk_user_id = lambda: int(uuid.uuid4().int % (10**10))  # Random 10-digit ID
    created_at = utcnow


class NationFactory(SQLAlchemyFactory[Nation]):
    """Factory for creating Nation instances."""
    
    __model__ = Nation
    
    id = lambda: str(uuid.uuid4())
    owner_player_id = None  # Set explicitly in tests
    name = "Test Nation"
    color_hex = "#FF0000"
    created_at = utcnow
    __set_foreign_keys__ = False


class ProvinceFactory(SQLAlchemyFactory[Province]):
    """Factory for creating Province instances."""
    
    __model__ = Province
    
    id = 1
    nation_id = None
    __set_foreign_keys__ = False


class GameClockFactory(SQLAlchemyFactory[GameClock]):
    """Factory for creating GameClock instances."""
    
    __model__ = GameClock
    
    id = 1
    current_turn = 0
    last_tick_at = None
    next_tick_at = utcnow


class ScheduledActionFactory(SQLAlchemyFactory[ScheduledAction]):
    """Factory for creating ScheduledAction instances."""
    
    __model__ = ScheduledAction
    
    id = lambda: str(uuid.uuid4())
    nation_id = None  # Set explicitly in tests
    module_slug = "test_module"
    action_type = "test_action"
    payload = {"test": "data"}
    turn_number = 1
    status = ScheduledActionStatus.PENDING
    created_at = utcnow
    applied_at = None
    __set_foreign_keys__ = False


class TickLogFactory(SQLAlchemyFactory[TickLog]):
    """Factory for creating TickLog instances."""
    
    __model__ = TickLog
    
    turn_number = 1
    started_at = utcnow
    finished_at = None
    status = TickLogStatus.RUNNING
    error_message = None
