"""
Tests for BotRuntime and the startup wiring (Spec 2.5; Appendix T:
T17, T18; INV-B2/B13).

OFF starts nothing; READY runs the four supervised tasks, sends a
queued notification end-to-end through the fake VK boundary, and
stops cleanly with leased rows returned. With every VK request
failing, a real tick still completes and game_clock advances — the
bot's failure domain never reaches the game.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from core.db import Base

from core.tick.orchestrator import TickOrchestrator
from modules._00_core.models import GameClock
from modules._00_core.tick_handler import finalize_tick
from modules._02_bot.models import BotOutbox
from modules._02_bot.runtime import BotRuntime
from modules._02_bot.settings import (
    BotMode,
    get_active_runtime,
    get_bot_mode,
    read_bot_env,
)
from modules._02_bot.signal import request_wake
from modules._02_bot.startup import start_runtime_if_ready
from tests.fixtures.fake_vk import FakeVk
from tests.modules._02_bot._issue3_support import (
    add_bot_state,
    add_member,
    add_outbox,
    make_session_factory,
)


@pytest.fixture(autouse=True)
def _orchestrator():
    TickOrchestrator.clear_handlers()
    TickOrchestrator.register_finalize(finalize_tick)
    yield
    TickOrchestrator.clear_handlers()


@pytest_asyncio.fixture
async def file_db_engine(tmp_path):
    """File-backed SQLite for runtime tests: a cancelled task's
    dropped connection must not take the whole in-memory schema with
    it (StaticPool :memory: artifact — production runs on a file or
    PostgreSQL, where the schema always survives)."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/bot_runtime.db"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


_DIGEST_VARS = {
    "turn": 1,
    "game_date": "2026-01-08",
    "nation_name": "N",
    "province_count": 1,
    "next_tick_time": "завтра",
}


async def _wait_for(predicate, timeout=8.0):
    """Poll a DB predicate with small real sleeps — waiting on a real
    background task, not faking time."""
    deadline = time.monotonic() + timeout
    while True:
        value = await predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the runtime")
        await asyncio.sleep(0.02)


class TestModes:
    async def test_off_starts_nothing(
        self, test_db_engine, bot_off_env, bot_config
    ):
        """BOT_ENABLED unset -> OFF: start_runtime_if_ready returns
        None and no runtime is registered."""
        sf = make_session_factory(test_db_engine)
        assert await start_runtime_if_ready(sf) is None
        assert get_active_runtime() is None
        assert get_bot_mode() is BotMode.OFF


class TestEndToEnd:
    async def test_ready_sends_one_notification(
        self, file_db_engine, bot_started
    ):
        """READY + fake VK: the runtime claims the queued row, sends
        it, writes SENT — and stop() leaves a clean queue."""
        sf = make_session_factory(file_db_engine)
        now = datetime.now(timezone.utc)
        async with sf() as session:
            player = await add_member(session)
            row = await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                created_at=now - timedelta(seconds=2),
                not_before=now - timedelta(seconds=2),
                next_attempt_at=now - timedelta(seconds=2),
                expires_at=now + timedelta(hours=1),
            )
            row_id = row.id
            await session.commit()

        fake = FakeVk()
        fake.respond_send_ok(message_id=9001)
        env = read_bot_env()
        runtime = BotRuntime(bot_started, env, sf, transport=fake.transport)
        await runtime.start()
        try:
            assert get_active_runtime() is runtime
            assert get_bot_mode(env) is BotMode.RUNNING
            assert runtime.sender_state() == "RUNNING"
            request_wake()

            async def _sent():
                async with sf() as session:
                    return (
                        await session.execute(
                            select(BotOutbox.status).where(
                                BotOutbox.id == row_id
                            )
                        )
                    ).scalar_one() == "SENT"

            await _wait_for(_sent)
            assert len(fake.send_requests()) == 1
            form = parse_qs(
                fake.send_requests()[0].content.decode()
            )
            assert int(form["random_id"][0]) == (
                (await _row(file_db_engine, row_id)).random_id
            )
            tasks = runtime.task_last_pass()
            assert tasks["sender"] is not None
        finally:
            await runtime.stop()

        assert get_active_runtime() is None
        assert get_bot_mode(env) is BotMode.READY
        async with sf() as session:
            leased = (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.status == "LEASED"
                    )
                )
            ).scalars().all()
        assert leased == []

    async def test_vk_down_tick_still_completes(
        self, file_db_engine, bot_started
    ):
        """T18: every VK request fails while the runtime is up — the
        real tick still completes, current_turn advances, and the
        watcher turns it into a digest row for the player."""
        sf = make_session_factory(file_db_engine)
        now = datetime.now(timezone.utc)
        async with sf() as session:
            session.add(
                GameClock(
                    id=1,
                    current_turn=0,
                    last_tick_at=None,
                    next_tick_at=now - timedelta(minutes=1),
                )
            )
            await add_bot_state(session, 0)
            player = await add_member(session, consent="ALLOWED")
            await session.commit()

        fake = FakeVk()
        fake.fail_connect()
        env = read_bot_env()
        runtime = BotRuntime(bot_started, env, sf, transport=fake.transport)
        await runtime.start()
        try:
            # The tick runs through the real path while VK is dead.
            async with sf() as session:
                outcome = await TickOrchestrator.run_tick(session)
                await session.commit()
            async with sf() as session:
                turn = (
                    await session.execute(
                        select(GameClock.current_turn)
                    )
                ).scalar_one()
            assert turn == 1

            # The watcher (its own task) sees turn 1 and enqueues the
            # digest; the sender keeps retrying it against dead VK.
            async def _digest_failed_once():
                async with sf() as session:
                    row = (
                        await session.execute(
                            select(BotOutbox).where(
                                BotOutbox.type_key == "TICK_DIGEST",
                                BotOutbox.player_id == player.id,
                            )
                        )
                    ).scalar_one_or_none()
                # last_error_code proves the failed send's write
                # transaction committed — the sender is back waiting
                # on the bell, so stop() cancels no in-flight DB work.
                return row is not None and row.last_error_code is not None

            assert await _wait_for(_digest_failed_once, timeout=12.0)
            # One scheduler-cycle margin before cancelling the tasks.
            await asyncio.sleep(0.2)
            # Nothing ever reached SENT — VK was down the whole time.
            async with sf() as session:
                sent = (
                    await session.execute(
                        select(BotOutbox.id).where(
                            BotOutbox.status == "SENT"
                        )
                    )
                ).scalars().all()
            assert sent == []
        finally:
            await runtime.stop()

        # The game side is untouched and the queue is healthy: leased
        # rows returned, only the digest waits for VK to come back.
        async with sf() as session:
            statuses = {
                row.status
                for row in (
                    await session.execute(select(BotOutbox))
                ).scalars()
            }
        assert statuses <= {"PENDING", "DROPPED", "FAILED"}


async def _row(engine, row_id) -> BotOutbox:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotOutbox).where(BotOutbox.id == row_id)
            )
        ).scalar_one()
