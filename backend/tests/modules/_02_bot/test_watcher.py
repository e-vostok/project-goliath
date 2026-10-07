"""
Tests for the digest watcher (Spec 3.8; Appendix T: T1, T18).

The turn is advanced by the real tick path (TickOrchestrator +
finalize_tick through run_scheduled_tick) on a real DB; the watcher
then enqueues exactly one TICK_DIGEST per eligible player through
BotService.enqueue. Covers the last_digest_turn compare-and-swap
(two steps, one winner), a failed tick leaving nothing, a stale tick
producing already-expired rows, and the deadline-warning path that
needs a registered audience provider.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from core.tick.orchestrator import TickOrchestrator, TickPhase
from modules._00_core.models import GameClock, Player
from modules._00_core.tick_handler import finalize_tick
from modules._02_bot.claim import claim_batch
from modules._02_bot.models import BotConsent, BotOutbox
from modules._02_bot.registry import register_deadline_audience
from modules._02_bot.settings import BotEnv
from modules._02_bot.watcher import digest_watcher_step
from tests.fixtures.profile import VALID_PROFILE
from tests.modules._02_bot._issue3_support import (
    NOW,
    add_bot_state,
    add_member,
    aware,
    make_session_factory,
)

ENV = BotEnv(
    enabled=True,
    group_id="12345",
    group_token="t",
    callback_secret="s",
    callback_confirmation="c",
    app_id=777,
)


@pytest.fixture(autouse=True)
def _orchestrator():
    TickOrchestrator.clear_handlers()
    TickOrchestrator.register_finalize(finalize_tick)
    yield
    TickOrchestrator.clear_handlers()


async def _seed_clock(session, *, turn=0, next_tick=NOW - timedelta(minutes=1),
                      last_tick=None):
    session.add(
        GameClock(
            id=1,
            current_turn=turn,
            last_tick_at=last_tick,
            next_tick_at=next_tick,
        )
    )
    await session.flush()


async def _rows(engine) -> list[BotOutbox]:
    async with make_session_factory(engine)() as session:
        result = await session.execute(select(BotOutbox))
        return list(result.scalars().all())


async def _digest_rows(engine) -> list[BotOutbox]:
    async with make_session_factory(engine)() as session:
        result = await session.execute(
            select(BotOutbox).where(
                BotOutbox.type_key == "TICK_DIGEST"
            )
        )
        return list(result.scalars().all())


class TestDigestAfterTick:
    async def test_one_digest_per_eligible_player(
        self, test_db_engine, bot_config, bot_started
    ):
        """T1: a committed tick -> one TICK_DIGEST per player that owns
        a nation AND consented; nobody else. A repeated step adds
        nothing."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            await _seed_clock(session)
            await add_bot_state(session, 0)
            member_ok = await add_member(session, consent="ALLOWED")
            await add_member(session, consent="UNKNOWN")
            await add_member(session, consent="DENIED")
            guest = await add_member(session, consent="ALLOWED")
            from modules._00_core.models import Nation

            nation = (
                await session.execute(
                    select(Nation).where(
                        Nation.owner_player_id == guest.id
                    )
                )
            ).scalar_one()
            await session.delete(nation)
            await session.commit()

            await TickOrchestrator.run_tick(session)
            await session.commit()

        await digest_watcher_step(sf, bot_config, now=NOW)
        rows = await _digest_rows(test_db_engine)
        assert len(rows) == 1
        row = rows[0]
        assert row.player_id == member_ok.id
        assert row.event_key == "turn:1"
        assert row.payload["turn"] == 1
        assert row.payload["nation_name"].startswith("N-")

        # A second pass is a no-op (compare-and-swap already moved).
        await digest_watcher_step(sf, bot_config, now=NOW)
        assert len(await _digest_rows(test_db_engine)) == 1

    async def test_failed_tick_leaves_nothing(
        self, test_db_engine, bot_config, bot_started
    ):
        """A handler that raises aborts the tick: the turn stays 0,
        and the watcher finds nothing to digest."""
        async def _boom(session, turn):
            raise RuntimeError("tick blew up")

        TickOrchestrator.register(
            TickPhase.PHASE_2_PRODUCTION, _boom
        )

        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            await _seed_clock(session)
            await add_bot_state(session, 0)
            await add_member(session, consent="ALLOWED")
            await session.commit()

            with pytest.raises(RuntimeError):
                await TickOrchestrator.run_tick(session)
            await session.rollback()

            clock = (
                await session.execute(select(GameClock))
            ).scalar_one()
            assert clock.current_turn == 0

        await digest_watcher_step(sf, bot_config, now=NOW)
        assert await _rows(test_db_engine) == []

    async def test_stale_tick_enqueues_expired_row(
        self, test_db_engine, bot_config, bot_started
    ):
        """A digest enqueued long after its tick is born expired —
        the claim flips it EXPIRED without ever calling VK."""
        stale_tick = NOW - timedelta(hours=10)  # ttl is 6h
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            session.add(
                GameClock(
                    id=1,
                    current_turn=3,
                    last_tick_at=stale_tick,
                    next_tick_at=NOW + timedelta(hours=14),
                )
            )
            await add_bot_state(session, 0)
            player = await add_member(session, consent="ALLOWED")
            await session.commit()

        await digest_watcher_step(sf, bot_config, now=NOW)
        rows = await _digest_rows(test_db_engine)
        assert len(rows) == 1
        assert aware(rows[0].expires_at) < NOW

        async with sf() as session:
            groups = await claim_batch(session, bot_config, ENV, NOW)
            await session.commit()
        assert groups == []
        assert (await _digest_rows(test_db_engine))[0].status == (
            "EXPIRED"
        )

    async def test_second_worker_loses_the_swap(
        self, test_db_engine, bot_config, bot_started
    ):
        """CAS: whichever transaction moves last_digest_turn first
        wins; the loser returns without enqueueing."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            session.add(
                GameClock(
                    id=1,
                    current_turn=7,
                    last_tick_at=NOW,
                    next_tick_at=NOW + timedelta(hours=23),
                )
            )
            await add_bot_state(session, 7)  # already digested
            await add_member(session, consent="ALLOWED")
            await session.commit()

        await digest_watcher_step(sf, bot_config, now=NOW)
        assert await _rows(test_db_engine) == []


class TestDeadlineWarning:
    async def _deadline_rows(self, engine) -> list[BotOutbox]:
        async with make_session_factory(engine)() as session:
            result = await session.execute(
                select(BotOutbox).where(
                    BotOutbox.type_key == "DEADLINE_WARNING"
                )
            )
            return list(result.scalars().all())

    async def test_deadline_only_with_provider_and_once(
        self, test_db_engine, bot_started
    ):
        """DEADLINE_WARNING fires inside its offset window, for the
        registered provider's audience, exactly once per turn.
        bot_isolation restores the provider list after the test."""
        # bot_started IS the startup-loaded config: enabling the type
        # here flips it for both the watcher and enqueue's own check.
        bot_config = bot_started
        bot_config.types["DEADLINE_WARNING"].enabled = True

        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            session.add(
                GameClock(
                    id=1,
                    current_turn=5,
                    last_tick_at=NOW - timedelta(hours=22),
                    next_tick_at=NOW + timedelta(hours=1),
                )
            )
            await add_bot_state(session, 5)  # digest already done
            member = await add_member(session, consent="ALLOWED")
            await session.commit()

        async def _audience(session, turn):
            return {member.id}

        register_deadline_audience(_audience)

        await digest_watcher_step(sf, bot_config, now=NOW)
        rows = await self._deadline_rows(test_db_engine)
        assert len(rows) == 1
        assert rows[0].event_key == "deadline:5"
        assert rows[0].player_id == member.id
        assert rows[0].payload["hours_left"] == 1

        # Once per turn.
        await digest_watcher_step(sf, bot_config, now=NOW)
        assert len(await self._deadline_rows(test_db_engine)) == 1

    async def test_no_provider_no_deadline(
        self, test_db_engine, bot_started
    ):
        """Without a registered audience provider the deadline part
        enqueues nothing even inside the window."""
        bot_config = bot_started
        bot_config.types["DEADLINE_WARNING"].enabled = True
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            session.add(
                GameClock(
                    id=1,
                    current_turn=5,
                    last_tick_at=NOW - timedelta(hours=22),
                    next_tick_at=NOW + timedelta(hours=1),
                )
            )
            await add_bot_state(session, 5)
            await add_member(session, consent="ALLOWED")
            await session.commit()

        await digest_watcher_step(sf, bot_config, now=NOW)
        assert await _rows(test_db_engine) == []
