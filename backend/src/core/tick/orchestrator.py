"""
Tick orchestration system for the game.

Provides the phase-based tick execution engine that all modules register
their handlers with. Ensures atomic execution and proper error logging.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TickPhase(enum.IntEnum):
    """Phases of a game tick execution in order."""
    
    PHASE_1_ENVIRONMENT = 100
    PHASE_2_PRODUCTION = 200
    PHASE_3_CONSUMPTION = 300
    PHASE_4_RESOLVE = 400
    PHASE_5_EXPIRATION = 500


class TickOrchestrator:
    """
    Orchestrates the execution of game ticks across all modules.
    
    Modules register their handlers for specific phases, and the
    orchestrator ensures they run in the correct order with proper
    transaction atomicity and error logging.
    """
    
    _handlers: dict[TickPhase, list[Callable[[AsyncSession, int], Awaitable[None]]]] = {}
    _finalize_callback: Callable[[AsyncSession, int], Awaitable[None]] | None = None
    
    @classmethod
    def register(
        cls,
        phase: TickPhase,
        handler: Callable[[AsyncSession, int], Awaitable[None]],
    ) -> None:
        """
        Register a handler for a specific tick phase.
        
        Args:
            phase: The phase to register the handler for.
            handler: Async function that takes (session, turn_number) and returns None.
        """
        if phase not in cls._handlers:
            cls._handlers[phase] = []
        cls._handlers[phase].append(handler)
        logger.info(f"Registered handler for phase {phase.name}")
    
    @classmethod
    def register_finalize(cls, callback: Callable[[AsyncSession, int], Awaitable[None]]) -> None:
        """
        Register the finalize callback that runs after all phases.
        
        Args:
            callback: Async function that takes (session, turn_number) and returns None.
        """
        cls._finalize_callback = callback
        logger.info("Registered finalize callback")
    
    @classmethod
    async def run_tick(cls, session: AsyncSession) -> None:
        """
        Execute a complete game tick.
        
        This method:
        1. Iterates through all TickPhase values in enum order
        2. Executes all handlers registered for each phase
        3. Calls finalize_tick() to increment the turn counter
        
        The entire operation is atomic - if any handler raises an exception,
        the transaction is rolled back and current_turn remains unchanged.
        On failure the session's transaction is rolled back inside this
        method (releasing the write lock) so the FAILED row can be recorded
        on a separate connection; callers passing an already-begun session
        should treat a raised exception as "the tick transaction was
        rolled back" and may still commit unrelated work afterwards.
        
        Args:
            session: The async session to use for the tick transaction.
                    This session is used for all phase handlers and finalize_tick.
        """
        from modules._00_core.models import GameClock, TickLog, TickLogStatus
        
        # Get the current turn number before starting
        clock_result = await session.execute(
            select(GameClock.current_turn).where(GameClock.id == 1)
        )
        current_turn = clock_result.scalar_one()
        next_turn = current_turn + 1
        
        # Create tick log entry using a SEPARATE session/connection.
        # This ensures the log survives a rollback of the main tick transaction.
        # session.bind returns the AsyncEngine the session is bound to.
        async_engine = session.bind
        async with AsyncSession(async_engine) as log_session:
            tick_log = TickLog(
                turn_number=next_turn,
                started_at=datetime.now(timezone.utc),
                status=TickLogStatus.RUNNING,
            )
            log_session.add(tick_log)
            await log_session.flush()
            tick_log_id = tick_log.id  # DB-assigned autoincrement id
            await log_session.commit()
        
        logger.info(f"Starting tick {next_turn}")
        
        try:
            # Execute all phase handlers in order
            for phase in TickPhase:
                handlers = cls._handlers.get(phase, [])
                for handler in handlers:
                    logger.debug(f"Executing handler for phase {phase.name}")
                    await handler(session, next_turn)
            
            # Finalize the tick (increment turn counter, update timestamps)
            if cls._finalize_callback is not None:
                await cls._finalize_callback(session, next_turn)
            
            # Update tick log as COMPLETED on the tick's own session, so it
            # commits atomically with the tick transaction. A second
            # connection would deadlock here on file-based SQLite, which
            # allows only one writer while this transaction is open.
            await session.execute(
                update(TickLog)
                .where(TickLog.id == tick_log_id)
                .values(
                    status=TickLogStatus.COMPLETED,
                    finished_at=datetime.now(timezone.utc)
                )
            )
            
            logger.info(f"Tick {next_turn} completed successfully")
            
        except Exception as e:
            # The caller owns the commit boundary, but the rollback must
            # happen here: only once the tick transaction releases its write
            # lock can a separate connection record the failure. On
            # file-based SQLite, writing FAILED before the rollback would
            # deadlock on the still-open transaction.
            await session.rollback()
            # Update tick log as FAILED using a separate session — it must
            # survive the rollback (INV-TICK-ATOMICITY).
            async with AsyncSession(async_engine) as log_session:
                await log_session.execute(
                    update(TickLog)
                    .where(TickLog.id == tick_log_id)
                    .values(
                        status=TickLogStatus.FAILED,
                        finished_at=datetime.now(timezone.utc),
                        error_message=str(e)
                    )
                )
                await log_session.commit()
            
            logger.error(f"Tick {next_turn} failed: {e}")
            # Re-raise to trigger transaction rollback
            raise
    
    @classmethod
    def clear_handlers(cls) -> None:
        """
        Clear all registered handlers.
        
        This is primarily useful for testing to ensure a clean state.
        """
        cls._handlers.clear()
