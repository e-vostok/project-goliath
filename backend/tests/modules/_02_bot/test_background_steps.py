"""
Tests for the consent reconciler and the janitor (Spec 3.7, 2.5).

Reconciler: UNKNOWN consents checked oldest-first through VK
isMessagesFromGroupAllowed under the limiter; True/False fold into
the FSM, None changes nothing — no game-state writes. Janitor: old
terminal rows and journal entries purge by purge_after_days, an
expired lease returns to PENDING, a live lease is untouched.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs

import pytest
from sqlalchemy import func, select

from modules._02_bot import consent as consent_mod
from modules._02_bot.janitor import janitor_step
from modules._02_bot.limiter import TokenBucket
from modules._02_bot.models import BotConsent, BotOutbox, BotVkEvent
from modules._02_bot.reconciler import reconcile_step
from modules._02_bot.settings import BotEnv
from modules._02_bot.vk_client import VkClient
from tests.fixtures.fake_vk import FakeVk
from tests.modules._02_bot._issue3_support import (
    NOW,
    add_consent,
    add_member,
    add_outbox,
    add_player,
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


class TestReconciler:
    async def test_unknown_folded_into_fsm(
        self, test_db_engine, bot_config
    ):
        """UNKNOWN -> ALLOWED on True, UNKNOWN -> DENIED on False,
        untouched on None; oldest checked first."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            oldest = await add_player(session, vk_user_id=100)
            await add_consent(
                session, oldest.id, state="UNKNOWN",
                created_at=NOW - timedelta(hours=2),
            )
            newer = await add_player(session, vk_user_id=200)
            await add_consent(
                session, newer.id, state="UNKNOWN",
                created_at=NOW - timedelta(hours=1),
            )
            flaky = await add_player(session, vk_user_id=300)
            await add_consent(session, flaky.id, state="UNKNOWN")
            allowed = await add_player(session, vk_user_id=400)
            await add_consent(session, allowed.id, state="ALLOWED")
            await session.commit()

        fake = FakeVk()
        fake.respond_allowed(True)
        fake.respond_allowed(False)
        fake.fail_timeout()
        vk = VkClient(
            bot_config, ENV.group_token, ENV.group_id,
            transport=fake.transport,
        )
        limiter = TokenBucket(1000)
        checked = await reconcile_step(sf, bot_config, ENV, vk, limiter)
        assert checked == 3

        # The ALLOWED consent was never checked: only 3 VK calls,
        # oldest first.
        user_ids = [
            parse_qs(r.content.decode())["user_id"][0]
            for r in fake.requests
        ]
        assert user_ids == ["100", "200", "300"]

        async with sf() as session:
            consents = {
                row.player_id: row
                for row in (
                    await session.execute(select(BotConsent))
                ).scalars()
            }
        assert consents[oldest.id].state == "ALLOWED"
        assert consents[oldest.id].state_source == "VK_CHECK"
        assert consents[oldest.id].last_checked_at is not None
        assert consents[newer.id].state == "DENIED"
        # The timed-out check changed nothing — not even the stamp.
        assert consents[flaky.id].state == "UNKNOWN"
        assert consents[flaky.id].last_checked_at is None

    async def test_denied_drops_pending_notifications(
        self, test_db_engine, bot_config
    ):
        """A False answer is a DENIED signal: the player's pending
        NOTIFICATION rows drop as NO_CONSENT (Spec 2.3)."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session, consent="UNKNOWN")
            await add_outbox(session, player.id, payload={})
            await session.commit()

        fake = FakeVk()
        fake.respond_allowed(False)
        vk = VkClient(
            bot_config, ENV.group_token, ENV.group_id,
            transport=fake.transport,
        )
        await reconcile_step(sf, bot_config, ENV, vk, TokenBucket(1000))
        async with sf() as session:
            row = (
                await session.execute(select(BotOutbox))
            ).scalar_one()
        assert row.status == "DROPPED"
        assert row.drop_reason == "NO_CONSENT"


class TestJanitor:
    async def test_purge_and_unstick(
        self, test_db_engine, bot_config
    ):
        sf = make_session_factory(test_db_engine)
        old = NOW - timedelta(
            days=bot_config.sender.purge_after_days, hours=1
        )
        async with sf() as session:
            player = await add_member(session)
            # Old terminal rows + journal entry -> purged.
            await add_outbox(
                session, player.id, status="SENT",
                sent_at=old, created_at=old,
            )
            await add_outbox(
                session, player.id, status="FAILED",
                drop_reason="ATTEMPTS_EXHAUSTED", created_at=old,
            )
            session.add(
                BotVkEvent(
                    event_id="evt-old",
                    event_type="message_new",
                    received_at=old,
                )
            )
            # A recent terminal row and a live lease -> kept.
            await add_outbox(
                session, player.id, status="DROPPED",
                drop_reason="NO_CONSENT",
            )
            stuck = await add_outbox(
                session, player.id, status="LEASED",
                lease_until=NOW - timedelta(minutes=5),
                lease_token="dead-token",
            )
            live = await add_outbox(
                session, player.id, status="LEASED",
                lease_until=NOW + timedelta(minutes=5),
                lease_token="live-token",
            )
            session.add(
                BotVkEvent(
                    event_id="evt-new",
                    event_type="message_new",
                    received_at=NOW,
                )
            )
            await session.commit()

        await janitor_step(sf, bot_config, now=NOW)

        async with sf() as session:
            rows = {
                row.id: row
                for row in (
                    await session.execute(select(BotOutbox))
                ).scalars()
            }
            events = (
                await session.execute(select(BotVkEvent.event_id))
            ).scalars().all()

        # Two old terminal rows purged; the recent DROPPED survives
        # alongside the two lease cases.
        assert len(rows) == 3
        assert rows[stuck.id].status == "PENDING"
        assert rows[stuck.id].lease_token is None
        assert rows[live.id].status == "LEASED"
        assert rows[live.id].lease_token == "live-token"
        assert events == ["evt-new"]
