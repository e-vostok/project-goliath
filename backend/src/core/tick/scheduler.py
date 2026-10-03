"""
Automatic tick scheduling for the game loop.

Wraps TickOrchestrator.run_tick() in a periodic asyncio loop driven by
game_clock.next_tick_at. A failed tick never stops the schedule: the
orchestrator already guarantees the failed attempt is atomic and recorded
in tick_log (INV-TICK-ATOMICITY), so the scheduler's only job is to keep
going. The loop itself is equally resilient: any transient error —
database down, missing game_clock row — is logged, paced on
retry_delay_seconds, and survived. heartbeat.touch() on every wake gives
health checks a "the loop is alive" stamp.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session_context
from core.tick import heartbeat
from core.tick.orchestrator import TickOrchestrator, TickOutcome

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def seconds_until(next_tick_at: datetime, now: datetime) -> float:
    """
    Seconds remaining until next_tick_at.

    Returns 0 when next_tick_at is already in the past (overdue tick),
    never a negative value.
    """
    return max(0.0, (next_tick_at - now).total_seconds())


async def run_scheduled_tick(
    session: AsyncSession, *, enforce_schedule: bool = False
) -> TickOutcome:
    """
    Run one game tick on the given session.

    Owns the transaction boundary: commits on success, rolls back on
    failure. Any exception is logged and swallowed — a failed tick must
    never crash the scheduler loop, and every attempt is kept in
    tick_log (multiple rows may share a turn_number).

    enforce_schedule=True is the automatic path: the orchestrator
    re-checks game_clock.next_tick_at under lock and may answer
    SKIPPED_NOT_DUE. enforce_schedule=False is the manual admin path and
    never skips on schedule (the advisory lock still applies).

    Returns the tick's TickOutcome, or FAILED on exception.
    """
    try:
        async with session.begin():
            return await TickOrchestrator.run_tick(
                session, enforce_schedule=enforce_schedule
            )
    except Exception:
        logger.exception("Scheduled tick failed")
        return TickOutcome.FAILED


async def _read_next_tick_at(
    session_factory: SessionFactory,
) -> datetime:
    """Committed game_clock.next_tick_at as a tz-aware UTC datetime."""
    from modules._00_core.models import GameClock

    async with session_factory() as session:
        result = await session.execute(
            select(GameClock.next_tick_at).where(GameClock.id == 1)
        )
        next_tick_at = result.scalar_one()

    # SQLite returns naive datetimes even for timezone=True columns.
    if next_tick_at.tzinfo is None:
        next_tick_at = next_tick_at.replace(tzinfo=timezone.utc)
    return next_tick_at


async def scheduler_loop(
    session_maker: SessionFactory | None = None,
    max_iterations: int | None = None,
    retry_delay_seconds: float | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> None:
    """
    Infinite tick loop: wait for game_clock.next_tick_at, fire, repeat.

    Each iteration opens fresh sessions via session_maker (defaults to
    core.db.get_session_context, the documented non-request entry point)
    and fires exactly one tick through run_scheduled_tick with
    enforce_schedule=True — the advisory lock plus the locked schedule
    re-check make a double run impossible even with two app instances.

    The wait is paced in chunks of at most heartbeat_interval_seconds,
    re-reading game_clock.next_tick_at on every wake, so a moved schedule
    (world reset, first-deploy alignment) is honoured within one interval
    instead of after the whole original wait. Every wake — and every
    handled error — stamps the liveness heartbeat.

    The whole iteration body is guarded by except Exception: a transient
    failure (DB unreachable, missing game_clock row, tick attempt raising
    past run_scheduled_tick) is logged and survived, paced on
    retry_delay_seconds so an overdue-but-failing tick cannot spin hot.
    asyncio.CancelledError is BaseException and propagates — shutdown is
    not a "handled error". The same retry pacing applies to any tick
    outcome other than EXECUTED (SKIPPED_*, FAILED).

    max_iterations bounds the loop for tests and counts tick attempts and
    handled errors — never sleep chunks. retry_delay_seconds and
    heartbeat_interval_seconds default to the tick.* keys in
    configs/00_core.yaml.
    """
    # Deferred imports mirror orchestrator.run_tick: keeps core.tick free
    # of import-time dependencies on modules.* (which import core.*).
    from modules._00_core.config_schema import CoreConfig

    session_factory = session_maker if session_maker is not None else get_session_context
    if retry_delay_seconds is None or heartbeat_interval_seconds is None:
        config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
        if retry_delay_seconds is None:
            retry_delay_seconds = config.tick.retry_delay_seconds
        if heartbeat_interval_seconds is None:
            heartbeat_interval_seconds = config.tick.heartbeat_interval_seconds
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        try:
            # Wait out the schedule in bounded chunks so a moved
            # next_tick_at is picked up within one heartbeat interval.
            while True:
                next_tick_at = await _read_next_tick_at(session_factory)
                delay = seconds_until(
                    next_tick_at, datetime.now(timezone.utc)
                )
                if delay <= 0:
                    break
                await asyncio.sleep(min(delay, heartbeat_interval_seconds))
                heartbeat.touch()

            async with session_factory() as session:
                outcome = await run_scheduled_tick(
                    session, enforce_schedule=True
                )
        except Exception:
            logger.exception(
                "Tick scheduler iteration failed; retrying in %ss",
                retry_delay_seconds,
            )
            heartbeat.touch()
            outcome = None

        iterations += 1

        if outcome is not TickOutcome.EXECUTED:
            await asyncio.sleep(retry_delay_seconds)
            heartbeat.touch()
