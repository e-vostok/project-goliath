"""
Tests for the send step (Spec 3.3, 2.7; Appendix T: T7, T9, T10,
T12, T23; INV-B6/B7/B9).

Real DB, VK through FakeVk (httpx.MockTransport), injected clocks —
no sleeps. Covers the retry loop with a stable random_id, every
error class behaviour, the keyboard chosen by nation state, critical
priority ordering, and the lease_token write guard.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from urllib.parse import parse_qs

import pytest
from sqlalchemy import select, update

from modules._02_bot.breaker import CircuitBreaker
from modules._02_bot.claim import claim_batch
from modules._02_bot.config_schema import BreakerSettings
from modules._02_bot.errors import ErrorClass
from modules._02_bot.limiter import TokenBucket
from modules._02_bot.models import BotConsent, BotOutbox
from modules._02_bot.sender import Sender
from modules._02_bot.settings import BotEnv
from modules._02_bot.vk_client import VkClient
from tests.fixtures.fake_vk import FakeVk, form_keyboard
from tests.modules._02_bot._issue3_support import (
    NOW,
    add_member,
    add_outbox,
    add_player,
    aware,
    make_session_factory,
    reply_payload,
)

ENV = BotEnv(
    enabled=True,
    group_id="12345",
    group_token="t",
    callback_secret="s",
    callback_confirmation="c",
    app_id=777,
)

_DIGEST_VARS = {
    "turn": 1,
    "game_date": "2026-01-08",
    "nation_name": "N",
    "province_count": 1,
    "next_tick_time": "завтра",
}


def _make_sender(bot_config, sf, fake: FakeVk, *, monotonic=None,
                 rng=lambda: 0.0, breaker_settings=None) -> Sender:
    clock = monotonic or (lambda: 0.0)

    async def _no_sleep(seconds: float) -> None:
        return None

    limiter = TokenBucket(1000, clock=clock, sleep=_no_sleep)
    breaker = CircuitBreaker(
        breaker_settings or bot_config.breaker, clock=clock
    )
    vk = VkClient(
        bot_config, ENV.group_token, ENV.group_id,
        transport=fake.transport,
    )
    return Sender(
        bot_config,
        ENV,
        sf,
        vk,
        limiter,
        breaker,
        monotonic=clock,
        now=lambda: NOW,
        rng=rng,
    )


async def _claim(engine, config, now=NOW):
    async with make_session_factory(engine)() as session:
        groups = await claim_batch(session, config, ENV, now)
        await session.commit()
    return groups


async def _row(engine, row_id) -> BotOutbox:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotOutbox).where(BotOutbox.id == row_id)
            )
        ).scalar_one()


def _send_random_ids(fake: FakeVk) -> list[int]:
    return [
        int(
            parse_qs(r.content.decode())["random_id"][0]
        )
        for r in fake.send_requests()
    ]


class TestRetry:
    async def test_timeout_then_success_same_random_id(
        self, test_db_engine, bot_config
    ):
        """T7/T12: attempt 1 times out, attempt 2 succeeds — the row
        carries attempts=2 and VK saw the same random_id both times
        (INV-B6)."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session)
            row = await add_outbox(
                session, player.id, payload=_DIGEST_VARS
            )
            row_id = row.id
            await session.commit()

        fake = FakeVk()
        sender = _make_sender(bot_config, sf, fake)

        fake.fail_timeout()
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "PENDING"
        assert aware(row.next_attempt_at) > NOW

        fake.respond_send_ok(message_id=77)
        groups = await _claim(
            test_db_engine, bot_config, now=NOW + timedelta(minutes=5)
        )
        await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "SENT"
        assert row.attempts == 2
        assert row.vk_message_id == 77
        assert row.last_error_code is None

        random_ids = _send_random_ids(fake)
        assert len(random_ids) == 2
        assert random_ids[0] == random_ids[1] == row.random_id


class TestErrorClasses:
    async def _seed_one(self, engine, **kw):
        sf = make_session_factory(engine)
        async with sf() as session:
            player = await add_member(session)
            row = await add_outbox(
                session, player.id, payload=_DIGEST_VARS, **kw
            )
            await session.commit()
        return sf, player, row.id

    async def test_901_drops_everything(
        self, test_db_engine, bot_config
    ):
        """T9: 901 -> consent DENIED, the sent group DROPPED/BLOCKED,
        the player's other pending rows dropped too, no retry."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session)
            ready = await add_outbox(
                session, player.id, payload=_DIGEST_VARS
            )
            pending = await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                not_before=NOW + timedelta(hours=1),
                next_attempt_at=NOW + timedelta(hours=1),
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_recipient_error(901)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])

        assert len(fake.send_requests()) == 1
        assert (await _row(test_db_engine, ready.id)).drop_reason == (
            "BLOCKED"
        )
        other = await _row(test_db_engine, pending.id)
        assert other.status == "DROPPED"
        assert other.drop_reason == "BLOCKED"
        async with sf() as session:
            consent = (
                await session.execute(
                    select(BotConsent).where(
                        BotConsent.player_id == player.id
                    )
                )
            ).scalar_one()
        assert consent.state == "DENIED"
        assert consent.state_source == "VK_ERROR_901"

    async def test_1021_no_consent(self, test_db_engine, bot_config):
        sf, player, row_id = await self._seed_one(test_db_engine)
        fake = FakeVk()
        fake.respond_recipient_error(1021)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "DROPPED"
        assert row.drop_reason == "NO_CONSENT"

    @pytest.mark.parametrize("code", [6, 29])
    async def test_rate_global_pauses_sender(
        self, test_db_engine, bot_config, code
    ):
        """6/29 -> rows back to PENDING with backoff AND a sender-wide
        pause: the next group does not even reach VK."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            first = await add_member(session)
            second = await add_member(session)
            for player in (first, second):
                await add_outbox(
                    session, player.id, payload=_DIGEST_VARS
                )
            await session.commit()

        fake = FakeVk()
        fake.respond_call_error(code)
        fake.respond_send_ok(9)
        monotonic = [0.0]
        sender = _make_sender(
            bot_config, sf, fake, monotonic=lambda: monotonic[0]
        )
        groups = await _claim(test_db_engine, bot_config)
        assert len(groups) == 2

        await sender.process_group(groups[0])
        await sender.process_group(groups[1])
        # The pause blocked the second group: only one VK call.
        assert len(fake.send_requests()) == 1
        assert sender.state.paused_until == pytest.approx(
            bot_config.sender.backoff_base_seconds
        )
        rows = [
            await _row(test_db_engine, g.row_ids[0]) for g in groups
        ]
        assert {r.status for r in rows} == {"PENDING", "LEASED"}

    async def test_flood_player_delays_only_that_player(
        self, test_db_engine, bot_config
    ):
        """9 -> retry for that player's rows only; others keep
        flowing (no sender pause, no breaker charge)."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            flooded = await add_member(session)
            calm = await add_member(session)
            a = await add_outbox(
                session, flooded.id, payload=_DIGEST_VARS
            )
            b = await add_outbox(
                session, calm.id, payload=_DIGEST_VARS
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_recipient_error(9)
        fake.respond_send_ok(5)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        by_player = {g.player_id: g for g in groups}
        await sender.process_group(by_player[flooded.id])
        await sender.process_group(by_player[calm.id])

        assert len(fake.send_requests()) == 2
        row_a = await _row(test_db_engine, a.id)
        assert row_a.status == "PENDING"
        assert row_a.last_error_code == 9
        assert aware(row_a.next_attempt_at) > NOW
        assert (await _row(test_db_engine, b.id)).status == "SENT"
        assert sender.state.paused_until == 0.0

    async def test_984_retries_and_logs_critical(
        self, test_db_engine, bot_config, caplog
    ):
        sf, player, row_id = await self._seed_one(test_db_engine)
        fake = FakeVk()
        fake.respond_call_error(984)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        with caplog.at_level(logging.CRITICAL):
            await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "PENDING"
        assert row.last_error_code == 984
        assert any(
            "984" in r.getMessage() for r in caplog.records
            if r.levelno >= logging.CRITICAL
        )

    async def test_984_counts_for_breaker(
        self, test_db_engine, bot_config
    ):
        sf, player, row_id = await self._seed_one(test_db_engine)
        fake = FakeVk()
        fake.respond_call_error(984)
        small = BreakerSettings(
            window_seconds=300,
            min_attempts=3,
            failure_ratio=0.5,
            open_seconds=120,
        )
        sender = _make_sender(
            bot_config, sf, fake, breaker_settings=small
        )
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])
        # Counted failures 2 and 3 (two fresh rows; the retried one is
        # still in backoff) open the breaker.
        for _ in range(2):
            async with sf() as session:
                await add_outbox(
                    session, player.id, payload=_DIGEST_VARS
                )
                await session.commit()
            groups = await _claim(test_db_engine, bot_config)
            await sender.process_group(groups[0])
        assert sender.status_word() == "BREAKER_OPEN"

    @pytest.mark.parametrize("code", [100, 911])
    async def test_bad_request_drops(
        self, test_db_engine, bot_config, code
    ):
        sf, player, row_id = await self._seed_one(test_db_engine)
        fake = FakeVk()
        fake.respond_call_error(code)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "DROPPED"
        assert row.drop_reason == "BAD_REQUEST"

    @pytest.mark.parametrize("code", [5, 27, 28])
    async def test_auth_halts_sender(
        self, test_db_engine, bot_config, code
    ):
        """5/27/28 -> HALTED_AUTH: no further VK calls, the rows wait
        in PENDING for a restart."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session)
            row = await add_outbox(
                session, player.id, payload=_DIGEST_VARS
            )
            row_id = row.id
            await session.commit()

        fake = FakeVk()
        fake.respond_call_error(code)
        fake.respond_send_ok(1)  # would succeed — must never be called
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        await sender.process_group(groups[0])
        assert sender.status_word() == "HALTED_AUTH"
        assert sender.state.halted_auth is True
        row = await _row(test_db_engine, row_id)
        assert row.status == "PENDING"
        assert row.last_error_code == code

        # A fresh claim (the row is PENDING again) must not reach VK.
        groups = await _claim(
            test_db_engine, bot_config, now=NOW + timedelta(minutes=5)
        )
        await sender.process_group(groups[0])
        assert len(fake.send_requests()) == 1


class TestKeyboard:
    async def test_keyboard_by_nation_and_help_reply(
        self, test_db_engine, bot_config
    ):
        """Spec 5.5: MEMBER/GUEST persistent keyboard at send time;
        a HELP reply carries the inline help keyboard instead."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            member = await add_member(session)
            await add_outbox(
                session, member.id, payload=_DIGEST_VARS
            )
            guest = await add_player(session)
            await add_outbox(
                session,
                guest.id,
                kind="REPLY",
                type_key="DIALOG",
                counts_toward_cap=False,
                payload=reply_payload("help", {}, "AUTO"),
            )
            asker = await add_player(session)
            await add_outbox(
                session,
                asker.id,
                kind="REPLY",
                type_key="DIALOG",
                counts_toward_cap=False,
                payload=reply_payload("help", {}, "HELP"),
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_send_ok(1)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        by_player = {g.player_id: g for g in groups}
        for player_id in (member.id, guest.id, asker.id):
            await sender.process_group(by_player[player_id])

        requests = fake.send_requests()
        assert len(requests) == 3
        member_kb = form_keyboard(requests[0])
        assert member_kb["buttons"][0][0]["action"]["type"] == "text"
        guest_kb = form_keyboard(requests[1])
        guest_actions = [
            btn["action"]["type"]
            for line in guest_kb["buttons"]
            for btn in line
        ]
        assert "open_app" in guest_actions
        help_kb = form_keyboard(requests[2])
        assert help_kb["inline"] is True
        help_actions = {
            btn["action"]["type"]
            for line in help_kb["buttons"]
            for btn in line
        }
        assert help_actions == {"open_link"}


class TestOrderingAndGuards:
    async def test_critical_sent_before_digest(
        self, test_db_engine, bot_config
    ):
        """T12: the critical alert claims and sends before the
        pending digest."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session)
            await add_outbox(
                session,
                player.id,
                payload=_DIGEST_VARS,
                created_at=NOW - timedelta(hours=1),
            )
            await add_outbox(
                session,
                player.id,
                type_key="RED_ALERT",
                priority="critical",
                counts_toward_cap=False,
                payload={"event_text": "удар"},
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_send_ok(1)
        sender = _make_sender(bot_config, sf, fake)
        groups = await _claim(test_db_engine, bot_config)
        assert groups[0].rows[0].priority == "critical"
        for group in groups:
            await sender.process_group(group)
        bodies = [
            parse_qs(r.content.decode())["message"][0]
            for r in fake.send_requests()
        ]
        assert "удар" in bodies[0]
        assert len(bodies) == 2

    async def test_changed_lease_token_writes_nothing(
        self, test_db_engine, bot_config, caplog
    ):
        """Spec 3.3 step 4: the result write targets only rows with
        our lease_token — a changed token means no send, no write."""
        sf = make_session_factory(test_db_engine)
        async with sf() as session:
            player = await add_member(session)
            row = await add_outbox(
                session, player.id, payload=_DIGEST_VARS
            )
            row_id = row.id
            await session.commit()

        groups = await _claim(test_db_engine, bot_config)
        async with sf() as session:
            await session.execute(
                update(BotOutbox)
                .where(BotOutbox.id == row_id)
                .values(lease_token="someone-else")
            )
            await session.commit()

        fake = FakeVk()
        fake.respond_send_ok(1)
        sender = _make_sender(bot_config, sf, fake)
        with caplog.at_level(logging.WARNING):
            await sender.process_group(groups[0])
        row = await _row(test_db_engine, row_id)
        assert row.status == "LEASED"  # untouched
        assert row.lease_token == "someone-else"
        assert len(fake.send_requests()) == 0
