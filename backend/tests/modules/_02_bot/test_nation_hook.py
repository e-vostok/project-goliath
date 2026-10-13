"""
The «nation created» hook of module 02_bot (Spec 3.11, Issue 7 — T26).

Real ``POST /api/v1/nations`` path, real DB; the only fake anywhere is
VK HTTP (none of these tests even reaches it — the hook never calls
VK). With an ``ALLOWED`` consent the creation queues exactly one
``REPLY`` row; every other consent state, a missing consent row and an
inactive bot queue nothing — and a raising hook never blocks the
registration.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select

import modules._02_bot.startup as startup_mod
from modules._00_core.models import Nation
from modules._02_bot.models import BotConsent, BotOutbox
from modules._02_bot.nation_hook import nation_created_hook
from modules._02_bot.service import BotService
from modules._02_bot.startup import startup_bot
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province
from tests.modules._02_bot._issue3_support import (
    add_consent,
    aware,
    make_session_factory,
)
from tests.modules._02_bot._issue4_support import (
    bearer_headers,
    seed_player,
)

pytest_plugins = ["tests.modules._02_bot._issue4_fixtures"]

NATIONS_URL = "/api/v1/nations"


@pytest.fixture
def bot_started_off(bot_off_env, bot_isolation):
    """startup_bot() over the OFF env — the hook registers but gates
    itself on the mode."""
    return startup_bot()


@pytest.fixture
def bot_misconfigured(monkeypatch, bot_isolation):
    """BOT_ENABLED on with the VK_* set missing -> MISCONFIGURED."""
    monkeypatch.setenv("BOT_ENABLED", "1")
    for name in (
        "VK_GROUP_ID",
        "VK_GROUP_TOKEN",
        "VK_CALLBACK_SECRET",
        "VK_CALLBACK_CONFIRMATION",
        "VK_APP_ID",
    ):
        monkeypatch.delenv(name, raising=False)
    return startup_bot()


@pytest.fixture
def consent_not_required(bot_started, monkeypatch):
    """Pin ``consent.required_for_registration`` to False so tests can
    register a nation without a prior consent row (the shipped default
    is True since v0.1.1). Mirrors the ``consent_required`` fixture."""
    config = bot_started.model_copy(
        update={
            "consent": bot_started.consent.model_copy(
                update={"required_for_registration": False}
            )
        }
    )
    monkeypatch.setattr(startup_mod, "_bot_config", config)
    return config


def _nation_body(name: str = "Государство Тестовое") -> dict:
    return {
        "name": name,
        "color_hex": "#A1B2C3",
        "province_ids": [1001, 1002],
        **VALID_PROFILE,
    }


async def _outbox_rows(engine) -> list[BotOutbox]:
    async with make_session_factory(engine)() as session:
        return list(
            (await session.execute(select(BotOutbox))).scalars().all()
        )


async def _consent(engine, player_id: str) -> BotConsent | None:
    async with make_session_factory(engine)() as session:
        return (
            await session.execute(
                select(BotConsent).where(
                    BotConsent.player_id == player_id
                )
            )
        ).scalar_one_or_none()


async def _create_nation(client, player) -> str:
    """One real registration; returns the new nation's id."""
    resp = await client.post(
        NATIONS_URL,
        headers=bearer_headers(player.id),
        json=_nation_body(),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


class TestNationCreatedHook:
    """Spec 3.11 over the real HTTP path (T26)."""

    async def test_allowed_enqueues_one_reply(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
    ):
        """ALLOWED + creation -> exactly one REPLY row, fully specified."""
        config = bot_started
        player = await seed_player(test_db_session, vk_user_id=770001)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)

        (row,) = await _outbox_rows(test_db_engine)
        assert row.player_id == player.id
        assert row.kind == "REPLY"
        assert row.type_key == "DIALOG"
        assert row.event_key == f"nation_created:{nation_id}"
        assert row.payload == {
            "template": "nation_created",
            "vars": {"nation_name": "Государство Тестовое"},
            "keyboard": "AUTO",
        }
        assert row.counts_toward_cap is False
        assert row.status == "PENDING"
        ttl = aware(row.expires_at) - aware(row.created_at)
        assert ttl == timedelta(minutes=config.dialog.reply_ttl_minutes)

    @pytest.mark.parametrize("state", ["UNKNOWN", "DENIED"])
    async def test_non_allowed_consent_enqueues_nothing(
        self,
        client,
        bot_started,
        consent_not_required,
        test_db_engine,
        test_db_session,
        state,
    ):
        """UNKNOWN/DENIED consent -> no reply row, consent untouched."""
        player = await seed_player(test_db_session, vk_user_id=770002)
        await add_consent(test_db_session, player.id, state=state)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)
        assert nation_id

        assert await _outbox_rows(test_db_engine) == []
        assert (await _consent(test_db_engine, player.id)).state == state

    async def test_no_consent_row_stays_rowless(
        self,
        client,
        bot_started,
        consent_not_required,
        test_db_engine,
        test_db_session,
    ):
        """No consent row -> no reply AND the hook creates no consent."""
        player = await seed_player(test_db_session, vk_user_id=770003)
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)
        assert nation_id

        assert await _outbox_rows(test_db_engine) == []
        assert await _consent(test_db_engine, player.id) is None

    async def test_bot_off_enqueues_nothing(
        self, client, bot_started_off, test_db_engine, test_db_session
    ):
        """OFF mode: even an ALLOWED player gets no row (bot silent)."""
        player = await seed_player(test_db_session, vk_user_id=770004)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)
        assert nation_id

        assert await _outbox_rows(test_db_engine) == []

    async def test_bot_misconfigured_enqueues_nothing(
        self,
        client,
        bot_misconfigured,
        test_db_engine,
        test_db_session,
    ):
        """MISCONFIGURED mode: no row either (Spec 3.11 step 1)."""
        player = await seed_player(test_db_session, vk_user_id=770005)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)
        assert nation_id

        assert await _outbox_rows(test_db_engine) == []

    async def test_second_call_same_nation_is_a_noop(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
    ):
        """The event_key dedup: invoking the hook again for the same
        nation adds nothing (UNIQUE behind a SAVEPOINT)."""
        player = await seed_player(test_db_session, vk_user_id=770006)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        nation_id = await _create_nation(client, player)
        await nation_created_hook(test_db_session, player.id, nation_id)
        await test_db_session.commit()

        rows = await _outbox_rows(test_db_engine)
        assert len(rows) == 1
        assert rows[0].event_key == f"nation_created:{nation_id}"

    async def test_hook_failure_never_blocks_creation(
        self,
        client,
        bot_started,
        test_db_engine,
        test_db_session,
        fake_vk_runtime,
        monkeypatch,
        caplog,
    ):
        """A raising hook is confined to its SAVEPOINT: the reply row it
        already wrote rolls back, the nation still commits, the HTTP
        response is the unchanged 201."""
        real_enqueue_reply = BotService.enqueue_reply

        async def _boom(session, **kwargs):
            # The real row lands inside the hook's SAVEPOINT; the raise
            # must roll it back with the rest of the hook's writes.
            await real_enqueue_reply(session, **kwargs)
            raise RuntimeError("injected hook failure")

        monkeypatch.setattr(
            BotService, "enqueue_reply", staticmethod(_boom)
        )

        player = await seed_player(test_db_session, vk_user_id=770007)
        await add_consent(test_db_session, player.id, state="ALLOWED")
        await make_land_province(test_db_session, id=1001)
        await make_land_province(test_db_session, id=1002)
        await test_db_session.commit()

        with caplog.at_level(logging.WARNING):
            nation_id = await _create_nation(client, player)

        assert nation_id
        assert "nation_created_hook_failed" in caplog.text
        assert "02_bot.nation_created" in caplog.text
        # No partial reply row survived the SAVEPOINT rollback.
        assert await _outbox_rows(test_db_engine) == []
        async with make_session_factory(test_db_engine)() as session:
            nation_count = (
                await session.execute(
                    select(func.count())
                    .select_from(Nation)
                    .where(Nation.owner_player_id == player.id)
                )
            ).scalar_one()
        assert nation_count == 1
