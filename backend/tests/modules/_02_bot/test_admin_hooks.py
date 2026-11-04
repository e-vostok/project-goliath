"""
Tests for the admin hooks of 02_bot (Spec 5.4, Appendix T: T16).

Reset wipes the queue and zeroes ``last_digest_turn`` while consents
and the vk-event journal survive (INV-B14); the state view reports a
JSON-able snapshot without env values or secrets; registration is
idempotent under the module slug ``02_bot``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from core.admin.router import admin_overview
from modules._00_core.models import Player
from modules._02_bot.admin_hooks import register_bot_admin_hooks
from modules._02_bot.models import BotConsent, BotOutbox, BotState
from tests.fixtures.factories import make_consent, make_outbox_row

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


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
        assert "02_bot" in AdminRegistry.get_overview_hooks()

    def test_repeated_registration_does_not_raise(self, bot_isolation):
        AdminRegistry.clear_handlers()
        register_bot_admin_hooks()
        register_bot_admin_hooks()
        assert len(AdminRegistry.get_state_view_hooks()) == 1
        assert len(AdminRegistry.get_reset_hooks()) == 1
        assert len(AdminRegistry.get_overview_hooks()) == 1


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
            await test_db_session.execute(select(func.count()).select_from(BotOutbox))
        ).scalar_one() == 0
        state = (
            await test_db_session.execute(select(BotState).where(BotState.id == 1))
        ).scalar_one()
        assert state.last_digest_turn == 0
        # Consents survive a world reset.
        assert (
            await test_db_session.execute(select(func.count()).select_from(BotConsent))
        ).scalar_one() == 1


class TestStateView:
    async def test_shape_without_secrets(self, test_db_session, bot_started):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        await make_consent(
            test_db_session,
            await _player(test_db_session),
            state="DENIED",
        )
        await make_outbox_row(test_db_session, player, status="PENDING")
        await make_outbox_row(
            test_db_session,
            player,
            status="DROPPED",
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

    async def test_empty_queue_has_null_age(self, test_db_session, bot_started):
        view = AdminRegistry.get_state_view_hooks()["02_bot"]
        snapshot = await view(test_db_session)
        assert snapshot["oldest_ready_age_seconds"] is None


class TestOverviewTiles:
    """The «Бот сообщества» tiles of «Ход и мир» (mockup 25)."""

    async def _tiles(self, session: AsyncSession) -> dict:
        hook = AdminRegistry.get_overview_hooks()["02_bot"]
        return {tile["key"]: tile for tile in await hook(session)}

    async def _outbox(
        self,
        session: AsyncSession,
        player: Player,
        *,
        status: str,
        created_at: datetime,
        drop_reason: str | None = None,
        not_before: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> BotOutbox:
        row = await make_outbox_row(
            session,
            player,
            status=status,
            drop_reason=drop_reason,
            created_at=created_at,
            not_before=not_before or created_at,
        )
        row.sent_at = sent_at
        await session.flush()
        return row

    async def test_counts_only_the_window(self, test_db_session, bot_started):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        sent_base = now - timedelta(minutes=10)
        await self._outbox(
            test_db_session,
            player,
            status="SENT",
            created_at=sent_base,
            sent_at=sent_base + timedelta(seconds=3),
        )
        await self._outbox(
            test_db_session,
            player,
            status="SENT",
            created_at=now - timedelta(days=2),
            sent_at=now - timedelta(hours=25),
        )
        await self._outbox(
            test_db_session,
            player,
            status="DROPPED",
            drop_reason="NO_CONSENT",
            created_at=now - timedelta(hours=2),
        )
        await self._outbox(
            test_db_session,
            player,
            status="FAILED",
            drop_reason="ATTEMPTS_EXHAUSTED",
            created_at=now - timedelta(hours=26),
        )
        await self._outbox(
            test_db_session,
            player,
            status="PENDING",
            created_at=now - timedelta(hours=1),
        )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_sent"]["value"] == "1"
        assert tiles["bot_undelivered"]["value"] == "1"
        assert tiles["bot_undelivered"]["note"] == "нет разрешения 1"
        assert [tile["sort"] for tile in tiles.values()] == [87, 88, 89]
        assert {tile["group"] for tile in tiles.values()} == {"bot"}

    async def test_cancelled_is_not_a_failure(self, test_db_session, bot_started):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        await self._outbox(
            test_db_session,
            player,
            status="DROPPED",
            drop_reason="CANCELLED",
            created_at=now - timedelta(hours=1),
        )
        await self._outbox(
            test_db_session,
            player,
            status="EXPIRED",
            created_at=now - timedelta(hours=1),
        )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_undelivered"]["value"] == "1"
        assert tiles["bot_undelivered"]["note"] == "просрочено 1"

    async def test_reasons_top_three_plus_other(
        self, test_db_session, bot_started
    ):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        for reason, rows in (
            ("NO_CONSENT", 4),
            ("BLOCKED", 3),
            ("ATTEMPTS_EXHAUSTED", 2),
            ("SOMETHING_NEW", 1),
        ):
            for _ in range(rows):
                await self._outbox(
                    test_db_session,
                    player,
                    status="DROPPED",
                    drop_reason=reason,
                    created_at=now - timedelta(hours=1),
                )
        await self._outbox(
            test_db_session,
            player,
            status="EXPIRED",
            created_at=now - timedelta(hours=1),
        )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_undelivered"]["value"] == "11"
        assert tiles["bot_undelivered"]["note"] == (
            "нет разрешения 4 · заблокирован 3 · попытки исчерпаны 2 · другое 2"
        )

    async def test_delivery_delay_median_odd_and_max(
        self, test_db_session, bot_started
    ):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        base = now - timedelta(minutes=30)
        for delay in (1.0, 2.4, 11.0):
            await self._outbox(
                test_db_session,
                player,
                status="SENT",
                created_at=base,
                sent_at=base + timedelta(seconds=delay),
            )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_delivery_delay"]["value"] == "2,4 с"
        assert (
            tiles["bot_delivery_delay"]["note"]
            == "медиана за сутки; наибольшая 11 с"
        )

    async def test_delivery_delay_median_even_and_minutes(
        self, test_db_session, bot_started
    ):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        base = now - timedelta(minutes=30)
        for delay in (11.0, 131.0):
            await self._outbox(
                test_db_session,
                player,
                status="SENT",
                created_at=base,
                sent_at=base + timedelta(seconds=delay),
            )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_delivery_delay"]["value"] == "71 с"
        assert (
            tiles["bot_delivery_delay"]["note"]
            == "медиана за сутки; наибольшая 2 мин"
        )

    async def test_delivery_delay_single_row(self, test_db_session, bot_started):
        now = datetime.now(UTC)
        player = await _player(test_db_session)
        base = now - timedelta(minutes=30)
        await self._outbox(
            test_db_session,
            player,
            status="SENT",
            created_at=base,
            sent_at=base + timedelta(seconds=5),
        )

        tiles = await self._tiles(test_db_session)

        assert tiles["bot_delivery_delay"]["value"] == "5,0 с"
        assert (
            tiles["bot_delivery_delay"]["note"]
            == "медиана за сутки; наибольшая 5,0 с"
        )

    async def test_empty_window(self, test_db_session, bot_started):
        tiles = await self._tiles(test_db_session)

        assert tiles["bot_sent"]["value"] == "0"
        assert tiles["bot_sent"]["note"] == "уведомления и ответы"
        assert tiles["bot_undelivered"]["value"] == "0"
        assert tiles["bot_undelivered"]["note"] == "ничего не потеряно"
        assert tiles["bot_delivery_delay"]["value"] == "—"
        assert (
            tiles["bot_delivery_delay"]["note"] == "за сутки ничего не отправлено"
        )

    async def test_failing_hook_leaves_other_tiles(
        self, test_db_session, bot_started
    ):
        """The endpoint's per-hook try/except skips a broken hook."""

        async def broken(session: AsyncSession) -> list[dict]:
            raise RuntimeError("boom")

        async def probe(session: AsyncSession) -> list[dict]:
            return [{"key": "probe", "label": "probe", "value": "1", "sort": 95}]

        AdminRegistry.register_overview("test_broken", broken)
        AdminRegistry.register_overview("test_probe", probe)
        player = await _player(test_db_session)
        base = datetime.now(UTC) - timedelta(minutes=5)
        await self._outbox(
            test_db_session,
            player,
            status="SENT",
            created_at=base,
            sent_at=base + timedelta(seconds=3),
        )

        tiles = await admin_overview(player, test_db_session)

        keys = [tile["key"] for tile in tiles]
        assert keys == ["bot_sent", "bot_undelivered", "bot_delivery_delay", "probe"]
        assert tiles[0]["value"] == "1"
