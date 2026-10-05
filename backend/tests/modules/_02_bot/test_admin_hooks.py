"""
Tests for the admin hooks of 02_bot (Spec 5.4, Appendix T: T16).

Reset wipes the queue and zeroes ``last_digest_turn`` while consents
and the vk-event journal survive (INV-B14); the state view reports a
JSON-able snapshot without env values or secrets; registration is
idempotent under the module slug ``02_bot``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.models import Player
from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.models import BotConsent, BotOutbox, BotState
from tests.fixtures.factories import make_consent, make_outbox_row

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


async def _player(session: AsyncSession) -> Player:
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=uuid.uuid4().int % 10**9,
        created_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


class TestRegistration:
    def test_registers_under_module_slug(self, bot_isolation):
        AdminRegistry.clear_handlers()
        register_bot_admin_hooks()
        assert "02_bot" in AdminRegistry.get_state_view_hooks()
        assert "02_bot" in AdminRegistry.get_reset_hooks()

    def test_repeated_registration_does_not_raise(self, bot_isolation):
        AdminRegistry.clear_handlers()
        register_bot_admin_hooks()
        register_bot_admin_hooks()
        assert len(AdminRegistry.get_state_view_hooks()) == 1
        assert len(AdminRegistry.get_reset_hooks()) == 1


class TestReset:
    async def test_reset_empties_queue_and_zeroes_turn(
        self, test_db_session, bot_started
    ):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        await make_outbox_row(test_db_session, player)
        await make_outbox_row(test_db_session, player)
        test_db_session.add(BotState(id=1, last_digest_turn=42))
        await test_db_session.flush()

        reset = AdminRegistry.get_reset_hooks()["02_bot"]
        await reset(test_db_session)

        assert (
            await test_db_session.execute(
                select(func.count()).select_from(BotOutbox)
            )
        ).scalar_one() == 0
        state = (
            await test_db_session.execute(
                select(BotState).where(BotState.id == 1)
            )
        ).scalar_one()
        assert state.last_digest_turn == 0
        # Consents survive a world reset.
        assert (
            await test_db_session.execute(
                select(func.count()).select_from(BotConsent)
            )
        ).scalar_one() == 1


class TestStateView:
    async def test_shape_without_secrets(
        self, test_db_session, bot_started
    ):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        await make_consent(
            test_db_session,
            await _player(test_db_session),
            state="DENIED",
        )
        await make_outbox_row(test_db_session, player, status="PENDING")
        await make_outbox_row(
            test_db_session, player, status="DROPPED",
            drop_reason="NO_CONSENT",
        )
        test_db_session.add(BotState(id=1, last_digest_turn=7))
        await test_db_session.flush()

        view = AdminRegistry.get_state_view_hooks()["02_bot"]
        snapshot = await view(test_db_session)

        assert snapshot["bot_mode"] == "READY"
        assert snapshot["consents"] == {"ALLOWED": 1, "DENIED": 1}
        assert snapshot["outbox"] == {"PENDING": 1, "DROPPED": 1}
        assert isinstance(snapshot["oldest_ready_age_seconds"], int)
        assert snapshot["last_digest_turn"] == 7
        assert snapshot["sender"] == "NOT_STARTED"
        # INV-B9: no env values leak into the admin view.
        as_text = str(snapshot)
        for secret in ("test-group-token", "test-callback-secret"):
            assert secret not in as_text

    async def test_empty_queue_has_null_age(
        self, test_db_session, bot_started
    ):
        view = AdminRegistry.get_state_view_hooks()["02_bot"]
        snapshot = await view(test_db_session)
        assert snapshot["oldest_ready_age_seconds"] is None
