"""
Tests for the automatic tick scheduler (Issue 6).

Real test DB throughout (Anti-Mock Guard): sessions come from a real
async_sessionmaker bound to the in-memory test engine — the same engine
run_tick's internal log sessions bind to. Wall-clock delay is controlled
by seeding next_tick_at in the past or by patching asyncio.sleep; both
exercise real code paths.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.tick.orchestrator import TickOrchestrator, TickPhase
from core.tick.scheduler import run_scheduled_tick, scheduler_loop, seconds_until
from main import app
from modules._00_core.models import GameClock, TickLog, TickLogStatus
from modules._00_core.tick_handler import register_tick_handlers
from tests.fixtures.factories import GameClockFactory
from tests.modules._00_core.test_router import TEST_JWT_SECRET, TEST_VK_SECRET

BACKEND_DIR = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def tick_handlers():
    """Wire the real finalize callback; clear phase handlers afterwards."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


@pytest_asyncio.fixture
async def session_maker(test_db_engine):
    """Session factory bound to the real in-memory test DB."""
    return async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )


async def _seed_game_clock(
    session_maker,
    next_tick_at: datetime | None = None,
    current_turn: int = 0,
) -> None:
    """Persist the game_clock singleton row via a real committed session."""
    clock = GameClockFactory.build(
        current_turn=current_turn,
        next_tick_at=next_tick_at or datetime.now(timezone.utc),
    )
    async with session_maker() as session:
        session.add(clock)
        await session.commit()


async def _fetch_clock(session_maker) -> GameClock:
    async with session_maker() as session:
        result = await session.execute(select(GameClock).where(GameClock.id == 1))
        return result.scalar_one()


class TestSecondsUntil:
    """Pure function: time remaining until the next tick."""

    def test_future_timestamp_returns_positive_seconds(self):
        now = datetime.now(timezone.utc)
        assert seconds_until(now + timedelta(hours=1), now) == 3600.0

    def test_past_timestamp_clamps_to_zero(self):
        now = datetime.now(timezone.utc)
        assert seconds_until(now - timedelta(hours=1), now) == 0.0


class TestRunScheduledTick:
    """One scheduled tick against the real DB."""

    @pytest.mark.asyncio
    async def test_happy_path_increments_current_turn(self, session_maker):
        await _seed_game_clock(session_maker)

        async with session_maker() as session:
            await run_scheduled_tick(session)

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 1
        assert clock.last_tick_at is not None

        async with session_maker() as session:
            result = await session.execute(
                select(TickLog).where(TickLog.turn_number == 1)
            )
            tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.COMPLETED
        assert tick_log.finished_at is not None

    @pytest.mark.asyncio
    async def test_failed_tick_returns_normally_and_next_tick_succeeds(
        self, session_maker
    ):
        """
        A handler that raises must not wedge the mechanism: the call
        returns normally, the turn is rolled back, tick_log shows FAILED,
        and the very next scheduled tick completes (INV-TICK-ATOMICITY).
        """
        await _seed_game_clock(session_maker)

        async def failing_handler(session, turn_number):
            raise ValueError("Simulated handler failure")

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, failing_handler)

        async with session_maker() as session:
            await run_scheduled_tick(session)  # must not raise

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 0

        async with session_maker() as session:
            result = await session.execute(
                select(TickLog).where(TickLog.turn_number == 1)
            )
            tick_log = result.scalar_one()
        assert tick_log.status == TickLogStatus.FAILED
        assert "Simulated handler failure" in tick_log.error_message

        # Transient failure resolved — the next scheduled tick succeeds.
        TickOrchestrator.clear_handlers()

        async with session_maker() as session:
            await run_scheduled_tick(session)

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 1

        async with session_maker() as session:
            result = await session.execute(
                select(TickLog).where(TickLog.turn_number == 1)
            )
            retry_log = result.scalar_one()
        assert retry_log.status == TickLogStatus.COMPLETED


class TestSchedulerLoop:
    """The bounded loop against the real DB."""

    @pytest.mark.asyncio
    async def test_two_iterations_increment_turn_twice(
        self, session_maker, monkeypatch
    ):
        """
        next_tick_at seeded in the past fires immediately (startup
        catch-up); asyncio.sleep is patched to a real zero-yield so the
        post-tick 24h cadence doesn't block the test — both iterations
        still execute real ticks on the real DB.
        """
        real_sleep = asyncio.sleep

        async def immediate_sleep(_delay: float) -> None:
            await real_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", immediate_sleep)

        await _seed_game_clock(
            session_maker,
            next_tick_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        await scheduler_loop(session_maker, max_iterations=2)

        clock = await _fetch_clock(session_maker)
        assert clock.current_turn == 2

        async with session_maker() as session:
            result = await session.execute(
                select(TickLog).order_by(TickLog.turn_number)
            )
            logs = result.scalars().all()
        assert len(logs) == 2
        assert [log.turn_number for log in logs] == [1, 2]
        assert all(log.status == TickLogStatus.COMPLETED for log in logs)


class TestLifespanWiring:
    """
    The scheduler task lives and dies with the app lifespan.

    Reuses the test_app_startup.py pattern: real app, real ASGI
    lifespan, real migrated SQLite file — the only path that exercises
    the production scheduler wiring.
    """

    @pytest.mark.asyncio
    async def test_scheduler_task_starts_and_cancels_cleanly(
        self, tmp_path, monkeypatch
    ):
        db_url = f"sqlite+aiosqlite:///{(tmp_path / 'scheduler.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
        monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)

        alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")

        async with LifespanManager(app):
            tasks = [
                t
                for t in asyncio.all_tasks()
                if t.get_name() == "tick-scheduler"
            ]
            assert len(tasks) == 1
            scheduler_task = tasks[0]
            assert not scheduler_task.done()

        # Shutdown must cancel it without leaking CancelledError.
        assert scheduler_task.cancelled()
