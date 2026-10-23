"""
Tests for BotService.enqueue (Spec 3.1, Appendix A/T: T2, T3, T17).

Real DB, real startup wiring (``bot_started`` runs startup_bot over a
READY env). Coverage: the ordered skip/reject ladder, the inserted
row's exact time fields, the dedup unique -> DUPLICATE mapping, an
already-expired row still inserting, and the one-shot after_commit
bell — silent on rollback, ringing on commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Nation, Player
from modules._02_bot.composer import ComposedMessage, RowView
from modules._02_bot.config_schema import BotConfig, TypeSettings
from modules._02_bot.models import BotOutbox
from modules._02_bot.registry import register_notification_type
from modules._02_bot.render import TemplateError, render_message
from modules._02_bot.service import BotService, EnqueueResult
from tests.fixtures.factories import make_consent, make_outbox_row
from tests.fixtures.profile import VALID_PROFILE

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _player(session: AsyncSession) -> Player:
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=uuid.uuid4().int % 10**9,
        created_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


async def _member(session: AsyncSession, *, consent: str | None = "ALLOWED") -> Player:
    """A player with a nation row and the given consent state."""
    player = await _player(session)
    session.add(
        Nation(
            id=str(uuid.uuid4()),
            owner_player_id=player.id,
            name=f"N-{player.id[:8]}",
            short_name=f"SN-{player.id[:8]}",
            color_hex="#" + uuid.uuid4().hex[:6].upper(),
            leader_name=VALID_PROFILE["leader_name"],
            leader_title=VALID_PROFILE["leader_title"],
            history_url=VALID_PROFILE["history_url"],
            created_at=NOW,
            created_turn=0,
        )
    )
    if consent is not None:
        await make_consent(session, player, state=consent)
    await session.flush()
    return player


async def _outbox_count(session: AsyncSession, player) -> int:
    """Count outbox rows; ``player`` may be a Player or a raw id."""
    player_id = player.id if isinstance(player, Player) else player
    result = await session.execute(
        select(func.count())
        .select_from(BotOutbox)
        .where(BotOutbox.player_id == player_id)
    )
    return result.scalar_one()


_DIGEST_VARS = {
    "turn": 7,
    "game_date": "Август 2040",
    "nation_name": "N",
    "province_count": 3,
    "next_tick_time": "завтра",
}

_DIRECTIVE_VARS = {"directive_title": "Д-1", "status_text": "в работе"}


def _add_type(
    config: BotConfig,
    key: str,
    variables: frozenset[str],
    *,
    requires_nation: bool,
    text: str,
) -> None:
    """Register a synthetic type in the live config and registry —
    the satellite-module dance of Spec 2.6 in miniature."""
    config.types[key] = TypeSettings(
        enabled=True,
        priority="normal",
        requires_consent=True,
        requires_nation=requires_nation,
        counts_toward_cap=False,
        ttl_minutes=60,
        hold_seconds=0,
        merge="never",
        max_per_window=0,
        window_minutes=60,
        text=text,
        batch_text=None,
        line_text=None,
    )
    register_notification_type(key, variables)


class TestQueued:
    async def test_queued_row_fields(self, test_db_session, bot_started):
        """DIRECTIVE_STATUS carries the hold_seconds showcase field."""
        player = await _member(test_db_session)
        result = await BotService.enqueue(
            test_db_session,
            type_key="DIRECTIVE_STATUS",
            player_id=player.id,
            event_key="directive:1",
            variables=_DIRECTIVE_VARS,
            now=NOW,
        )
        assert result == EnqueueResult.QUEUED

        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.player_id == player.id)
            )
        ).scalar_one()
        assert row.kind == "NOTIFICATION"
        assert row.status == "PENDING"
        assert row.attempts == 0
        assert row.priority == "normal"
        assert row.counts_toward_cap is True
        assert row.payload == _DIRECTIVE_VARS
        # hold_seconds = 120: the merge window of status changes.
        assert _aware(row.not_before) == NOW + timedelta(seconds=120)
        assert row.next_attempt_at == row.not_before
        # ttl_minutes = 2880 from event time (t0 = t here).
        assert _aware(row.expires_at) == NOW + timedelta(minutes=2880)
        assert _aware(row.created_at) == NOW

    async def test_distant_event_at_inserts_expired_row(
        self, test_db_session, bot_started
    ):
        """A stale digest still lands — expires_at just reads past."""
        player = await _member(test_db_session)
        event_at = NOW - timedelta(days=2)
        result = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:1",
            variables=_DIGEST_VARS,
            event_at=event_at,
            now=NOW,
        )
        assert result == EnqueueResult.QUEUED
        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.player_id == player.id)
            )
        ).scalar_one()
        assert _aware(row.expires_at) == event_at + timedelta(minutes=360)
        assert _aware(row.expires_at) < NOW

    async def test_duplicate_event_key(self, test_db_session, bot_started):
        player = await _member(test_db_session)
        first = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:7",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        second = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:7",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        assert first == EnqueueResult.QUEUED
        assert second == EnqueueResult.DUPLICATE
        assert await _outbox_count(test_db_session, player) == 1


class TestSkipsAndRejects:
    async def test_bot_off_writes_nothing(
        self, test_db_session, bot_isolation, bot_off_env
    ):
        player = await _player(test_db_session)
        result = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:7",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        assert result == EnqueueResult.SKIPPED_BOT_OFF
        assert await _outbox_count(test_db_session, player) == 0

    async def test_disabled_type_skipped(self, test_db_session, bot_started):
        """DEADLINE_WARNING ships disabled in the real config."""
        player = await _member(test_db_session)
        result = await BotService.enqueue(
            test_db_session,
            type_key="DEADLINE_WARNING",
            player_id=player.id,
            event_key="deadline:7",
            variables={"hours_left": 3},
            now=NOW,
        )
        assert result == EnqueueResult.SKIPPED_TYPE_DISABLED
        assert await _outbox_count(test_db_session, player) == 0

    async def test_no_nation_skipped(self, test_db_session, bot_started):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        result = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:7",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        assert result == EnqueueResult.SKIPPED_NO_NATION
        assert await _outbox_count(test_db_session, player) == 0

    async def test_no_consent_skipped(self, test_db_session, bot_started):
        """No consent row counts as UNKNOWN -> SKIPPED_NO_CONSENT."""
        player = await _member(test_db_session, consent=None)
        result = await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=player.id,
            event_key="turn:7",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        assert result == EnqueueResult.SKIPPED_NO_CONSENT
        assert await _outbox_count(test_db_session, player) == 0

    @pytest.mark.parametrize(
        "type_key,variables",
        [
            ("GHOST_TYPE", {}),  # unregistered
            ("TICK_DIGEST", {"turn": 7}),  # missing vars
            (
                "TICK_DIGEST",
                _DIGEST_VARS | {"extra": "x"},
            ),  # surplus var
            (
                "TICK_DIGEST",
                _DIGEST_VARS | {"turn": True},
            ),  # bool is rejected
        ],
    )
    async def test_rejected_invalid(
        self, test_db_session, bot_started, type_key, variables
    ):
        player = await _member(test_db_session)
        result = await BotService.enqueue(
            test_db_session,
            type_key=type_key,
            player_id=player.id,
            event_key="e:1",
            variables=variables,
            now=NOW,
        )
        assert result == EnqueueResult.REJECTED_INVALID
        assert await _outbox_count(test_db_session, player) == 0


class TestWakeBell:
    async def test_commit_rings_rollback_does_not(
        self, test_db_session, bot_started, wake_event
    ):
        player = await _member(test_db_session)
        pid = player.id  # captured before rollback expires the object
        # Persist the fixture rows so the rollback below drops only the
        # enqueued row, not the player/nation/consent behind it.
        await test_db_session.commit()

        await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=pid,
            event_key="turn:1",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        await test_db_session.rollback()
        assert wake_event.is_set() is False
        assert await _outbox_count(test_db_session, pid) == 0

        await BotService.enqueue(
            test_db_session,
            type_key="TICK_DIGEST",
            player_id=pid,
            event_key="turn:2",
            variables=_DIGEST_VARS,
            now=NOW,
        )
        await test_db_session.commit()
        assert wake_event.is_set() is True
        assert await _outbox_count(test_db_session, pid) == 1


class TestRequiresNation:
    """types.<KEY>.requires_nation (Spec 04_orders, Appendix B2)."""

    async def test_guest_accepted_for_nationless_type(
        self, test_db_session, bot_started
    ):
        """A requires_nation=false type queues for a nationless player;
        the builtin types still gate on a nation."""
        _add_type(
            bot_started,
            "GUEST_PING",
            frozenset({"ping"}),
            requires_nation=False,
            text="Пинг: {ping}.",
        )
        guest = await _player(test_db_session)
        await make_consent(test_db_session, guest, state="ALLOWED")

        result = await BotService.enqueue(
            test_db_session,
            type_key="GUEST_PING",
            player_id=guest.id,
            event_key="ping:1",
            variables={"ping": "pong"},
            now=NOW,
        )
        assert result == EnqueueResult.QUEUED
        assert await _outbox_count(test_db_session, guest) == 1

        # An existing requires_nation type refuses the same player.
        skipped = await BotService.enqueue(
            test_db_session,
            type_key="RED_ALERT",
            player_id=guest.id,
            event_key="alert:1",
            variables={"event_text": "тест"},
            now=NOW,
        )
        assert skipped == EnqueueResult.SKIPPED_NO_NATION
        assert await _outbox_count(test_db_session, guest) == 1


class TestConsentedPlayerIds:
    """BotService.consented_player_ids (Spec 04_orders, Appendix B2)."""

    async def test_allowed_subset_and_empty_input(self, test_db_session, bot_started):
        allowed = await _player(test_db_session)
        denied = await _player(test_db_session)
        unknown = await _player(test_db_session)
        await make_consent(test_db_session, allowed, state="ALLOWED")
        await make_consent(test_db_session, denied, state="DENIED")
        await make_consent(test_db_session, unknown, state="UNKNOWN")

        ids = await BotService.consented_player_ids(
            test_db_session, [allowed.id, denied.id, unknown.id]
        )
        assert ids == {allowed.id}
        assert await BotService.consented_player_ids(test_db_session, []) == set()

    async def test_empty_when_bot_off(
        self, test_db_session, bot_isolation, bot_off_env
    ):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        assert (
            await BotService.consented_player_ids(test_db_session, [player.id]) == set()
        )


class TestAppLink:
    """BotService.app_link (Spec 04_orders, Appendix B2)."""

    def test_link_and_missing_app_id(self, bot_env, monkeypatch):
        # The bot_env fixture sets VK_APP_ID=777.
        assert BotService.app_link("registry/order-5") == (
            "https://vk.com/app777#registry/order-5"
        )
        monkeypatch.delenv("VK_APP_ID")
        assert BotService.app_link("register") is None
        monkeypatch.setenv("VK_APP_ID", "not-a-number")
        assert BotService.app_link("register") is None


class TestLinkVariables:
    """``*_link`` variables (Spec 04_orders, Appendix B2): validated at
    enqueue, re-validated at render, substituted verbatim."""

    async def test_invalid_rejected_valid_verbatim(self, test_db_session, bot_started):
        _add_type(
            bot_started,
            "ORDER_LINK",
            frozenset({"order_link"}),
            requires_nation=False,
            text="Приказ: {order_link}",
        )
        member = await _member(test_db_session)

        for bad in (
            "http://vk.com/app777#x",  # not https
            "https://example.com/app777#x",  # host not allowed
            "https://vk.com/" + "a" * 300,  # over 300 chars
            "not a url",
        ):
            result = await BotService.enqueue(
                test_db_session,
                type_key="ORDER_LINK",
                player_id=member.id,
                event_key=f"bad:{bad[:16]}",
                variables={"order_link": bad},
                now=NOW,
            )
            assert result == EnqueueResult.REJECTED_INVALID
        assert await _outbox_count(test_db_session, member) == 0

        # Brackets would be remapped by sanitize_value — surviving
        # verbatim proves the link path skips it.
        link = "https://vk.com/app777#registry/order-[5]"
        ok = await BotService.enqueue(
            test_db_session,
            type_key="ORDER_LINK",
            player_id=member.id,
            event_key="ok:1",
            variables={"order_link": link},
            now=NOW,
        )
        assert ok == EnqueueResult.QUEUED

        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.player_id == member.id)
            )
        ).scalar_one()
        view = RowView(
            id=row.id,
            type_key=row.type_key,
            kind=row.kind,
            priority=row.priority,
            counts_toward_cap=row.counts_toward_cap,
            created_at=row.created_at,
            not_before=row.not_before,
            next_attempt_at=row.next_attempt_at,
            expires_at=row.expires_at,
            payload=row.payload,
        )
        text = render_message(
            ComposedMessage((row.id,), "SINGLE", "ORDER_LINK", False),
            {row.id: view},
            bot_started,
        )
        assert text == f"Приказ: {link}"

        # A bad value already in the payload is re-validated at render:
        # it can never reach a message (dropped as TEMPLATE_ERROR).
        broken = await make_outbox_row(
            test_db_session,
            member,
            type_key="ORDER_LINK",
            payload={"order_link": "http://vk.com/app777#x"},
        )
        broken_view = RowView(
            id=broken.id,
            type_key=broken.type_key,
            kind=broken.kind,
            priority=broken.priority,
            counts_toward_cap=broken.counts_toward_cap,
            created_at=broken.created_at,
            not_before=broken.not_before,
            next_attempt_at=broken.next_attempt_at,
            expires_at=broken.expires_at,
            payload=broken.payload,
        )
        with pytest.raises(TemplateError):
            render_message(
                ComposedMessage((broken.id,), "SINGLE", "ORDER_LINK", False),
                {broken.id: broken_view},
                bot_started,
            )
