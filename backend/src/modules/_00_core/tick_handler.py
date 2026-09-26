"""
Tick handler for module 00_core.

Provides the finalize_tick function that is called by the TickOrchestrator
after all phase handlers have completed successfully.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.tick.orchestrator import TickOrchestrator
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import GameClock


async def finalize_tick(session: AsyncSession, turn_number: int) -> None:
    """
    Finalize a tick by updating the game clock.
    
    This function:
    - Increments current_turn to the given turn_number
    - Sets last_tick_at to now
    - Sets next_tick_at to now + tick_interval_hours
    
    Args:
        session: The async database session.
        turn_number: The turn number that just completed.
    """
    # Load the core config
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    
    # Get the game clock (singleton, id=1)
    result = await session.execute(
        select(GameClock).where(GameClock.id == 1)
    )
    clock = result.scalar_one()
    
    # Update the clock
    now = datetime.now(timezone.utc)
    clock.current_turn = turn_number
    clock.last_tick_at = now
    clock.next_tick_at = now + timedelta(hours=config.tick.tick_interval_hours)
    
    # Flush to ensure the changes are applied
    await session.flush()


def register_tick_handlers() -> None:
    """
    Register the 00_core tick handlers with the TickOrchestrator.
    
    This function should be called during application startup to ensure
    the finalize_tick callback is registered.
    """
    TickOrchestrator.register_finalize(finalize_tick)
