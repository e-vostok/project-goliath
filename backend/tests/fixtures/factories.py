"""
Polyfactory factories for 00_core models.

Provides test data factories for Player, Nation, and Province models.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory

from modules._00_core.models import Nation, Player, Province


class PlayerFactory(SQLAlchemyFactory[Player]):
    """Factory for creating Player instances."""
    
    __model__ = Player
    
    id = lambda: str(uuid.uuid4())
    vk_user_id = 1234567890
    created_at = datetime.now(timezone.utc)


class NationFactory(SQLAlchemyFactory[Nation]):
    """Factory for creating Nation instances."""
    
    __model__ = Nation
    
    id = lambda: str(uuid.uuid4())
    owner_player_id = None  # Set explicitly in tests
    name = "Test Nation"
    color_hex = "#FF0000"
    created_at = datetime.now(timezone.utc)
    __set_foreign_keys__ = False


class ProvinceFactory(SQLAlchemyFactory[Province]):
    """Factory for creating Province instances."""
    
    __model__ = Province
    
    id = 1
    nation_id = None
    __set_foreign_keys__ = False
