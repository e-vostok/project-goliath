"""
Tick safety on real PostgreSQL (deploy spec §7, Issue DEP-3).

Proves the cross-process guarantees SQLite cannot express: the
pg_try_advisory_xact_lock mutex (two app instances overlapping during a
deploy, a manual admin run racing the scheduler), the locked
next_tick_at re-check, and that a skipped attempt writes nothing — not
even a RUNNING row.

Real DB only (Anti-Mock Guard): pg_db sessions are independent asyncpg
connections on a migrated, wiped *_test database; pg_live_client serves
the real app through its real lifespan.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text, update

from core.tick.orchestrator import (
    TICK_ADVISORY_LOCK_KEY,
    TickOrchestrator,
    TickOutcome,
    TickPhase,
)
from core.tick.scheduler import run_scheduled_tick
from modules._00_core.models import GameClock, TickLog, TickLogStatus
from modules._00_core.tick_handler import register_tick_handlers
from tests.fixtures.postgres import (
    ADMIN_VK_ID,
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_live_client,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.modules._00_core.test_router import (
    TEST_VK_SECRET,
    make_launch_params,
)

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def tick_handlers():
    """Wire the real finalize callback; clear phase handlers afterwards."""
    TickOrchestrator.clear_handlers()
    register_tick_handlers()
    yield
    TickOrchestrator.clear_handlers()


async def _make_overdue(pg_db) -> None:
    """pg_clean leaves next_tick_at a day out — pull it into the past."""
    async with pg_db() as session:
        await session.execute(
            update(GameClock)
            .where(GameClock.id == 1)
            .values(
                next_tick_at=datetime.now(timezone.utc)
                - timedelta(minutes=1)
            )
        )
        await session.commit()


async def _clock(pg_db) -> GameClock:
    async with pg_db() as session:
        result = await session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        return result.scalar_one()


async def _tick_logs(pg_db) -> list[TickLog]:
    async with pg_db() as session:
        result = await session.execute(select(TickLog).order_by(TickLog.id))
        return list(result.scalars().all())


async def _acquire_advisory_lock(session) -> None:
    """Session-level advisory lock held by `session`'s own connection —
    a second backend instance holding the tick mutex."""
    await session.execute(
        text("SELECT pg_advisory_lock(:key)"),
        {"key": TICK_ADVISORY_LOCK_KEY},
    )


async def _release_advisory_lock(session) -> None:
    """Explicit unlock: session-level advisory locks survive a pooled
    connection's return-to-pool, so relying on close() would leak."""
    await session.execute(
        text("SELECT pg_advisory_unlock(:key)"),
        {"key": TICK_ADVISORY_LOCK_KEY},
    )


class TestAdvisoryLock:
    """The tick mutex across connections and processes."""

    async def test_concurrent_scheduled_ticks_run_exactly_once(self, pg_db):
        """
        Two simultaneous automatic ticks on two sessions: the winner's
        0.5s phase handler holds the transaction (and the advisory lock)
        open while the loser's pg_try fails. Exactly one EXECUTED, one
        SKIPPED_LOCKED, one COMPLETED tick_log row, no RUNNING residue.
        """
        await _make_overdue(pg_db)

        async def slow_handler(session, turn_number):
            await asyncio.sleep(0.5)

        TickOrchestrator.register(TickPhase.PHASE_1_ENVIRONMENT, slow_handler)

        async with pg_db() as session_a, pg_db() as session_b:
            outcomes = await asyncio.gather(
                run_scheduled_tick(session_a, enforce_schedule=True),
                run_scheduled_tick(session_b, enforce_schedule=True),
            )

        assert sorted(outcome.name for outcome in outcomes) == [
            "EXECUTED",
            "SKIPPED_LOCKED",
        ]
        assert (await _clock(pg_db)).current_turn == 1
        logs = await _tick_logs(pg_db)
        assert len(logs) == 1
        assert logs[0].turn_number == 1
        assert logs[0].status == TickLogStatus.COMPLETED
        assert logs[0].finished_at is not None

    async def test_lock_held_by_other_connection_skips_cleanly(self, pg_db):
        """
        pg_advisory_lock taken on a raw second connection: run_tick
        answers SKIPPED_LOCKED and writes nothing. Releasing the lock
        lets the very next attempt execute.
        """
        await _make_overdue(pg_db)

        async with pg_db() as blocker:
            await _acquire_advisory_lock(blocker)

            async with pg_db() as tick_session:
                outcome = await run_scheduled_tick(
                    tick_session, enforce_schedule=True
                )
            assert outcome is TickOutcome.SKIPPED_LOCKED
            assert await _tick_logs(pg_db) == []
            assert (await _clock(pg_db)).current_turn == 0

            await _release_advisory_lock(blocker)

        async with pg_db() as tick_session:
            outcome = await run_scheduled_tick(
                tick_session, enforce_schedule=True
            )
        assert outcome is TickOutcome.EXECUTED
        assert (await _clock(pg_db)).current_turn == 1
        logs = await _tick_logs(pg_db)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED

    async def test_failed_tick_releases_lock_for_next_attempt(self, pg_db):
        """
        A blowing phase handler rolls the tick transaction back — which
        also frees the transaction-scoped advisory lock: the FAILED row
        is recorded, current_turn is unchanged, and the next attempt
        executes instead of skipping forever.
        """
        await _make_overdue(pg_db)

        async def exploding_handler(session, turn_number):
            raise RuntimeError("phase exploded")

        TickOrchestrator.register(
            TickPhase.PHASE_1_ENVIRONMENT, exploding_handler
        )

        async with pg_db() as session:
            outcome = await run_scheduled_tick(
                session, enforce_schedule=True
            )
        assert outcome is TickOutcome.FAILED
        assert (await _clock(pg_db)).current_turn == 0
        logs = await _tick_logs(pg_db)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.FAILED
        assert "phase exploded" in logs[0].error_message

        # Lock is free again: a clean retry executes on the still-overdue
        # slot and the FAILED row stays as attempt history.
        TickOrchestrator.clear_handlers()
        async with pg_db() as session:
            outcome = await run_scheduled_tick(
                session, enforce_schedule=True
            )
        assert outcome is TickOutcome.EXECUTED
        assert (await _clock(pg_db)).current_turn == 1
        logs = await _tick_logs(pg_db)
        assert [log.status for log in logs] == [
            TickLogStatus.FAILED,
            TickLogStatus.COMPLETED,
        ]


class TestScheduleRecheck:
    """The locked next_tick_at re-check on the automatic path."""

    async def test_second_automatic_call_skips_not_due(self, pg_db):
        """
        After a served slot, finalize wrote a future next_tick_at: the
        loser's FOR UPDATE read sees it and answers SKIPPED_NOT_DUE —
        no extra tick_log row, current_turn untouched. This is the
        deploy overlap caught late (lock acquired after the winner's
        commit).
        """
        await _make_overdue(pg_db)

        async with pg_db() as session:
            first = await run_scheduled_tick(session, enforce_schedule=True)
        assert first is TickOutcome.EXECUTED

        async with pg_db() as session:
            second = await run_scheduled_tick(
                session, enforce_schedule=True
            )
        assert second is TickOutcome.SKIPPED_NOT_DUE

        assert (await _clock(pg_db)).current_turn == 1
        logs = await _tick_logs(pg_db)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED

    async def test_future_slot_auto_skips_manual_executes(self, pg_db):
        """
        pg_clean leaves next_tick_at a day out: the automatic path skips
        (SKIPPED_NOT_DUE, nothing written) while the manual admin path —
        enforce_schedule=False — still takes the lock and runs.
        """
        async with pg_db() as session:
            outcome = await run_scheduled_tick(
                session, enforce_schedule=True
            )
        assert outcome is TickOutcome.SKIPPED_NOT_DUE
        assert await _tick_logs(pg_db) == []
        assert (await _clock(pg_db)).current_turn == 0

        async with pg_db() as session:
            manual = await run_scheduled_tick(
                session, enforce_schedule=False
            )
        assert manual is TickOutcome.EXECUTED
        assert (await _clock(pg_db)).current_turn == 1
        logs = await _tick_logs(pg_db)
        assert len(logs) == 1
        assert logs[0].status == TickLogStatus.COMPLETED


class TestAdminTickRunConflict:
    """POST /api/v1/admin/tick/run against a busy tick mutex."""

    async def test_manual_run_returns_409_when_lock_held(
        self, pg_live_client, pg_db
    ):
        """
        Another connection holding the advisory lock -> the manual run
        answers 409 TICK_IN_PROGRESS. After the unlock the same endpoint
        runs the tick normally.
        """
        client = pg_live_client
        resp = await client.post(
            "/api/v1/auth/vk",
            json={
                "launch_params": make_launch_params(
                    vk_user_id=ADMIN_VK_ID, secret=TEST_VK_SECRET
                )
            },
        )
        assert resp.status_code == 200
        headers = {
            "Authorization": f"Bearer {resp.json()['access_token']}"
        }

        async with pg_db() as blocker:
            await _acquire_advisory_lock(blocker)

            tick = await client.post(
                "/api/v1/admin/tick/run", headers=headers
            )
            assert tick.status_code == 409
            assert tick.json()["code"] == "TICK_IN_PROGRESS"

            # The busy attempt wrote nothing.
            async with pg_db() as session:
                count = await session.execute(
                    select(func.count()).select_from(TickLog)
                )
                assert count.scalar_one() == 0

            await _release_advisory_lock(blocker)

        tick = await client.post(
            "/api/v1/admin/tick/run", headers=headers
        )
        assert tick.status_code == 200
        body = tick.json()
        assert body["ok"] is True
        assert body["current_turn"] == 1
        assert body["tick_log"]["status"] == TickLogStatus.COMPLETED.value
