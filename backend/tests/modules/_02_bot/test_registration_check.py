"""
Registration consent gate tests — Spec 3.10, Appendix T: T21.

The real ``POST /api/v1/nations`` path runs the ``before_all`` stage:
an explicit VK «not allowed» blocks with 403 ``CONSENT_REQUIRED`` and
the DENIED state stays durable; every other failure — VK down,
timeout, open breaker, ``HALTED_AUTH``, no runtime — fails open with a
WARNING (INV-B15).
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select

from modules._00_core.models import Nation
from modules._02_bot.models import BotConsent
from modules._02_bot.runtime import install_runtime
from modules._02_bot.startup import get_bot_config, startup_bot
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province
from tests.modules._02_bot._issue3_support import (
    add_consent,
    make_session_factory,
)
from tests.modules._02_bot._issue4_support import (
    bearer_headers,
    seed_player,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]

NATIONS_URL = "/api/v1/nations"


def _nation_body(name: str = "Государство Тестовое") -> dict:
    return {
        "name": name,
        "color_hex": "#A1B2C3",
        "province_ids": [1001, 1002],
        **VALID_PROFILE,
    }


async def _nation_count(session, player_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Nation)
            .where(Nation.owner_player_id == player_id)
        )
    ).scalar_one()


async def _consent_durable(engine, player_id: str) -> BotConsent:
    """The consent row re-read in a FRESH session — proof the state
    survived the rejected registration's rollback (Spec 3.10 step 4)."""
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotConsent).where(
                    BotConsent.player_id == player_id
                )
            )
        ).scalar_one()


@pytest.fixture
def bot_started_off(bot_off_env, bot_isolation):
    """startup_bot() over the OFF env — the check registers but gates
    itself on the mode."""
    return startup_bot()


class TestConsentGate:
    """Spec 3.10 steps 2–4 over the real HTTP path."""

    async def test_allowed_creates_nation_no_vk(
        self,
        client,
        bot_started,
        test_db_session,
        fake_vk_runtime,
    ):
        fake, _runtime = fake_vk_runtime
        player = await seed_player(test_db_session, vk_user_id=880001)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 201
        assert fake.requests == []

    async def test_vk_denied_403_consent_persists(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
    ):
        fake, _runtime = fake_vk_runtime
        fake.respond_allowed(False)
        player = await seed_player(test_db_session, vk_user_id=880002)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "CONSENT_REQUIRED"
        assert await _nation_count(test_db_session, player.id) == 0
        # The commit inside the check kept the new DENIED state and
        # last_checked_at durable past the rejection.
        row = await _consent_durable(test_db_engine, player.id)
        assert row.state == "DENIED"
        assert row.state_source == "VK_CHECK"
        assert row.last_checked_at is not None

        # A second attempt inside refresh_min_interval_seconds: 403
        # without another VK call.
        resp2 = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp2.status_code == 403
        assert len(fake.requests) == 1

    async def test_vk_allowed_creates_nation(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
    ):
        fake, _runtime = fake_vk_runtime
        fake.respond_allowed(True)
        player = await seed_player(test_db_session, vk_user_id=880003)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 201
        row = await _consent_durable(test_db_engine, player.id)
        assert row.state == "ALLOWED"
        assert len(fake.requests) == 1


class TestFailOpen:
    """INV-B15: VK troubles never block registration."""

    @pytest.mark.parametrize(
        "failure",
        ["connect", "timeout", "breaker_open", "halted_auth", "no_runtime"],
    )
    async def test_registration_succeeds_on_vk_trouble(
        self,
        client,
        bot_started,
        test_db_session,
        fake_vk_runtime,
        caplog,
        failure,
    ):
        fake, runtime = fake_vk_runtime
        if failure == "connect":
            for _ in range(3):
                fake.fail_connect()
        elif failure == "timeout":
            for _ in range(3):
                fake.fail_timeout()
        elif failure == "breaker_open":
            # breaker.min_attempts=10 counted failures open the window.
            for _ in range(12):
                runtime._breaker.record(success=False, counts=True)
        elif failure == "halted_auth":
            runtime._sender.state.halted_auth = True
        else:  # no_runtime
            install_runtime(None)

        player = await seed_player(test_db_session, vk_user_id=880004)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        with caplog.at_level(logging.WARNING):
            resp = await client.post(
                NATIONS_URL,
                headers=bearer_headers(player.id),
                json=_nation_body(),
            )
        assert resp.status_code == 201
        assert "registration_consent_check_skipped" in caplog.text


class TestDisabledPaths:
    """Spec 3.10 step 1: the gate is a no-op when it must not act."""

    async def test_bot_off_creates_nation_no_vk(
        self, client, bot_started_off, test_db_session
    ):
        player = await seed_player(test_db_session, vk_user_id=880005)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 201

    async def test_required_false_creates_nation_no_vk(
        self,
        client,
        bot_started,
        test_db_session,
        fake_vk_runtime,
        monkeypatch,
    ):
        fake, _runtime = fake_vk_runtime
        config = get_bot_config()
        patched = config.model_copy(
            update={
                "consent": config.consent.model_copy(
                    update={"required_for_registration": False}
                )
            }
        )
        # The check resolves get_bot_config lazily via the module —
        # patch the module attribute it will fetch.
        import modules._02_bot.startup as startup_mod

        monkeypatch.setattr(startup_mod, "get_bot_config", lambda: patched)

        player = await seed_player(test_db_session, vk_user_id=880006)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        resp = await client.post(
            NATIONS_URL,
            headers=bearer_headers(player.id),
            json=_nation_body(),
        )
        assert resp.status_code == 201
        assert fake.requests == []
