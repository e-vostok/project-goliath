"""
Status and consent-refresh endpoint tests — Spec 3.7/5.2, T24.

Real DB; VK through ``FakeVk`` on a prepared (not started) runtime.
Covers the OFF-mode contract, the lazy/forced VK check rules, the
minimum-interval throttle, ``stale`` on VK failure and the DTO's
interval/chat_url fields. Secrets never appear in responses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from modules._02_bot.models import BotConsent
from tests.modules._02_bot._issue3_support import (
    add_consent,
    add_player,
)
from tests.modules._02_bot._issue4_support import (
    bearer_headers,
    seed_player,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]

STATUS_URL = "/api/v1/bot/status"
REFRESH_URL = "/api/v1/bot/consent/refresh"

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class TestBotOff:
    """With the bot off the module is invisible (Spec 5.2)."""

    async def test_get_status_disabled(
        self, client, bot_off_env, test_db_session
    ):
        player = await seed_player(test_db_session)
        await test_db_session.commit()
        resp = await client.get(
            STATUS_URL, headers=bearer_headers(player.id)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is False
        assert body["consent"] == "UNKNOWN"
        assert body["stale"] is False
        assert body["throttled"] is False
        assert body["registration_requires_consent"] is False
        assert body["chat_url"] is None
        assert body["consent_poll_interval_seconds"] is None
        assert body["consent_poll_timeout_seconds"] is None
        # No consent row is created while the bot is off.
        rows = (
            await test_db_session.execute(select(BotConsent))
        ).scalars().all()
        assert rows == []

    async def test_post_refresh_disabled_409(
        self, client, bot_off_env, test_db_session
    ):
        player = await seed_player(test_db_session)
        await test_db_session.commit()
        resp = await client.post(
            REFRESH_URL, headers=bearer_headers(player.id)
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "BOT_DISABLED"


class TestActive:
    """READY bot: the DTO and the Spec 3.7 VK check rules."""

    async def test_status_fields_and_one_lazy_check(
        self, client, bot_started, test_db_session, fake_vk_runtime
    ):
        fake, _runtime = fake_vk_runtime
        fake.respond_allowed(True)
        player = await seed_player(test_db_session, vk_user_id=777001)
        await test_db_session.commit()

        resp = await client.get(
            STATUS_URL, headers=bearer_headers(player.id)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        assert body["consent"] == "ALLOWED"
        assert body["stale"] is False
        assert body["throttled"] is False
        assert body["registration_requires_consent"] is True
        assert "12345" in body["chat_url"]
        assert body["consent_poll_interval_seconds"] == 3
        assert body["consent_poll_timeout_seconds"] == 90
        # Secrets never leak into the response.
        blob = resp.text
        assert "test-group-token" not in blob
        assert "test-callback-secret" not in blob
        # The UNKNOWN state triggered exactly one VK check...
        assert len(fake.requests) == 1
        # ...and a second GET within the minimum interval does not.
        resp2 = await client.get(
            STATUS_URL, headers=bearer_headers(player.id)
        )
        assert resp2.json()["consent"] == "ALLOWED"
        assert len(fake.requests) == 1

    async def test_post_twice_within_interval_throttled(
        self, client, bot_started, test_db_session, fake_vk_runtime
    ):
        fake, _runtime = fake_vk_runtime
        fake.respond_allowed(False)
        player = await seed_player(test_db_session, vk_user_id=777002)
        await test_db_session.commit()

        first = await client.post(
            REFRESH_URL, headers=bearer_headers(player.id)
        )
        assert first.status_code == 200
        assert first.json()["consent"] == "DENIED"
        assert first.json()["throttled"] is False
        assert len(fake.requests) == 1

        second = await client.post(
            REFRESH_URL, headers=bearer_headers(player.id)
        )
        assert second.json()["throttled"] is True
        assert second.json()["consent"] == "DENIED"
        assert len(fake.requests) == 1  # no second VK call

    async def test_vk_failure_returns_stored_state_stale(
        self, client, bot_started, test_db_session, fake_vk_runtime
    ):
        fake, _runtime = fake_vk_runtime
        fake.fail_connect()
        player = await seed_player(test_db_session, vk_user_id=777003)
        await test_db_session.commit()

        resp = await client.get(
            STATUS_URL, headers=bearer_headers(player.id)
        )
        body = resp.json()
        assert body["consent"] == "UNKNOWN"
        assert body["stale"] is True

    async def test_fresh_allowed_no_vk_call(
        self, client, bot_started, test_db_session, fake_vk_runtime
    ):
        fake, _runtime = fake_vk_runtime
        player = await add_player(test_db_session, vk_user_id=777004)
        consent = await add_consent(
            test_db_session, player.id, state="ALLOWED"
        )
        consent.last_checked_at = datetime.now(timezone.utc)
        await test_db_session.commit()

        resp = await client.get(
            STATUS_URL, headers=bearer_headers(player.id)
        )
        assert resp.json()["consent"] == "ALLOWED"
        assert resp.json()["stale"] is False
        assert fake.requests == []

    async def test_missing_bearer_401(self, client, bot_started):
        resp = await client.get(STATUS_URL)
        assert resp.status_code == 401
        resp = await client.post(REFRESH_URL)
        assert resp.status_code == 401
