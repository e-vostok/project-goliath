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

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# PostgreSQL advisory-lock key serializing ticks across every process
# that shares the database ('GOLIATH' as ASCII hex). Must fit bigint.
TICK_ADVISORY_LOCK_KEY = 0x474F4C49415448


class TickPhase(enum.IntEnum):
    """Phases of a game tick execution in order."""
    
    PHASE_1_ENVIRONMENT = 100
    PHASE_2_PRODUCTION = 200
    PHASE_3_CONSUMPTION = 300
    PHASE_4_RESOLVE = 400
    PHASE_5_EXPIRATION = 500


class TickOutcome(enum.Enum):
    """Result of a single run_tick call.

    SKIPPED_* outcomes mean nothing was read or written beyond the lock
    probes — in particular no tick_log row exists for a skipped attempt.
    A failed tick is not an outcome: it still raises.
    """

    EXECUTED = "EXECUTED"
    SKIPPED_LOCKED = "SKIPPED_LOCKED"
    SKIPPED_NOT_DUE = "SKIPPED_NOT_DUE"
    FAILED = "FAILED"


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
    async def run_tick(
        cls, session: AsyncSession, *, enforce_schedule: bool = False
    ) -> TickOutcome:
        """
        Execute a complete game tick.
        
        Before anything is read or written:
        1. On PostgreSQL, take pg_try_advisory_xact_lock on
           TICK_ADVISORY_LOCK_KEY inside the caller's transaction — a
           second concurrent tick (overlapping deploy, admin manual run
           racing the scheduler) gets SKIPPED_LOCKED instead of running
           the phases a second time. The lock is transaction-scoped: the
           caller's commit or the internal failure rollback releases it.
           Skipped on SQLite (single-process test dialect).
        2. Read game_clock.next_tick_at under SELECT ... FOR UPDATE so a
           winner's committed schedule is visible to the loser. With
           enforce_schedule=True a next_tick_at still in the future means
           the slot was already served — SKIPPED_NOT_DUE. The manual path
           (enforce_schedule=False) skips only this re-check, not the
           advisory lock.
        
        An executed tick then:
        1. Iterates through all TickPhase values in enum order
        2. Executes all handlers registered for each phase
        3. Calls finalize_tick() to increment the turn counter
        
        The entire operation is atomic - if any handler raises an exception,
        the transaction is rolled back and current_turn remains unchanged.
        On failure the session's transaction is rolled back inside this
        method (releasing the write lock and the advisory lock) so the
        FAILED row can be recorded on a separate connection; callers
        passing an already-begun session should treat a raised exception
        as "the tick transaction was rolled back" and may still commit
        unrelated work afterwards.
        
        Args:
            session: The async session to use for the tick transaction.
                    This session is used for all phase handlers and finalize_tick.
            enforce_schedule: When True, skip the tick if game_clock says
                    the slot is not yet due (scheduler path). When False
                    (manual admin run) always proceed once the lock is held.
        
        Returns:
            TickOutcome.EXECUTED, SKIPPED_LOCKED or SKIPPED_NOT_DUE.
            Failures raise as before.
        """
        from modules._00_core.models import GameClock, TickLog, TickLogStatus
        
        # 1. Cross-process tick mutex — the very first statement, before
        # any read or the RUNNING row (a loser must leave no trace).
        if session.bind.dialect.name == "postgresql":
            lock_result = await session.execute(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": TICK_ADVISORY_LOCK_KEY},
            )
            if not lock_result.scalar_one():
                logger.info("Tick skipped: advisory lock already held")
                return TickOutcome.SKIPPED_LOCKED
        
        # 2. Lock the clock row for the whole tick transaction and, for
        # the automatic path, re-check the schedule under that lock.
        clock_row = await session.execute(
            select(GameClock.next_tick_at)
            .where(GameClock.id == 1)
            .with_for_update()
        )
        next_tick_at = clock_row.scalar_one()
        if enforce_schedule:
            # SQLite returns naive datetimes even for timezone=True columns.
            if next_tick_at.tzinfo is None:
                next_tick_at = next_tick_at.replace(tzinfo=timezone.utc)
            if next_tick_at > datetime.now(timezone.utc):
                logger.info(
                    "Tick skipped: not due until %s", next_tick_at
                )
                return TickOutcome.SKIPPED_NOT_DUE
        
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
            return TickOutcome.EXECUTED
            
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
