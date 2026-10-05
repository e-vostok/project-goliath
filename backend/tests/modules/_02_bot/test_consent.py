"""
Tests for the consent FSM of 02_bot (Spec 2.3, Appendix T).

Real DB only: transitions, drop-on-DENIED (BLOCKED vs NO_CONSENT,
untouched REPLY/SENT/other-player rows), no resurrection on ALLOWED,
and record_vk_check semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Player
from modules._02_bot.consent import (
    apply_consent_signal,
    get_or_create_consent,
    is_allowed,
    record_vk_check,
)
from modules._02_bot.models import BotConsent, BotOutbox
from tests.fixtures.factories import make_consent, make_outbox_row

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes even for timezone=True columns."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _player(session: AsyncSession) -> Player:
    player = Player(
        id=str(uuid.uuid4()), vk_user_id=uuid.uuid4().int % 10**9,
        created_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


class TestGetOrCreate:
    async def test_creates_unknown_init(self, test_db_session):
        player = await _player(test_db_session)
        consent = await get_or_create_consent(
            test_db_session, player.id, now=NOW
        )
        assert consent.state == "UNKNOWN"
        assert consent.state_source == "INIT"
        assert consent.state_changed_at == NOW
        again = await get_or_create_consent(
            test_db_session, player.id, now=NOW + timedelta(hours=1)
        )
        assert again.player_id == consent.player_id

    async def test_is_allowed_states(self, test_db_session):
        player = await _player(test_db_session)
        assert await is_allowed(test_db_session, player.id) is False
        await make_consent(test_db_session, player, state="ALLOWED")
        assert await is_allowed(test_db_session, player.id) is True


class TestTransitions:
    """All four FSM transitions of Spec 2.3 are legal."""

    @pytest.mark.parametrize(
        "initial,new_state",
        [
            ("UNKNOWN", "ALLOWED"),
            ("UNKNOWN", "DENIED"),
            ("ALLOWED", "DENIED"),
            ("DENIED", "ALLOWED"),
        ],
    )
    async def test_legal_transition(
        self, test_db_session, initial, new_state
    ):
        player = await _player(test_db_session)
        await make_consent(
            test_db_session,
            player,
            state=initial,
            state_changed_at=NOW - timedelta(hours=1),
        )
        result = await apply_consent_signal(
            test_db_session, player.id, new_state, "VK_EVENT", now=NOW
        )
        assert (result.old, result.new, result.changed) == (
            initial,
            new_state,
            True,
        )
        consent = await get_or_create_consent(test_db_session, player.id)
        assert consent.state == new_state
        assert consent.state_source == "VK_EVENT"
        assert _aware(consent.state_changed_at) == NOW

    async def test_same_state_keeps_state_changed_at(
        self, test_db_session
    ):
        player = await _player(test_db_session)
        earlier = NOW - timedelta(hours=3)
        await make_consent(
            test_db_session, player, state="DENIED",
            state_source="VK_EVENT", state_changed_at=earlier,
        )
        result = await apply_consent_signal(
            test_db_session, player.id, "DENIED", "VK_EVENT", now=NOW
        )
        assert result.changed is False
        consent = await get_or_create_consent(test_db_session, player.id)
        assert _aware(consent.state_changed_at) == earlier
        assert consent.state_source == "VK_EVENT"

    async def test_vk_check_always_refreshes_last_checked(
        self, test_db_session
    ):
        player = await _player(test_db_session)
        await make_consent(
            test_db_session, player, state="ALLOWED",
            state_source="VK_CHECK",
            last_checked_at=NOW - timedelta(hours=1),
        )
        # ALLOWED -> ALLOWED does not move state_changed_at but a
        # VK_CHECK still records the check time.
        result = await apply_consent_signal(
            test_db_session, player.id, "ALLOWED", "VK_CHECK", now=NOW
        )
        assert result.changed is False
        consent = await get_or_create_consent(test_db_session, player.id)
        assert _aware(consent.last_checked_at) == NOW

    async def test_signal_on_unknown_creates_row(self, test_db_session):
        player = await _player(test_db_session)
        result = await apply_consent_signal(
            test_db_session, player.id, "ALLOWED", "VK_EVENT", now=NOW
        )
        assert (result.old, result.new, result.changed) == (
            "UNKNOWN",
            "ALLOWED",
            True,
        )

    @pytest.mark.parametrize(
        "new_state,source",
        [
            ("UNKNOWN", "VK_EVENT"),   # UNKNOWN is never a signal target
            ("ALLOWED", "INIT"),       # INIT is a row seed, not a signal
            ("ALLOWED", "SOMETHING"),
        ],
    )
    async def test_illegal_arguments_rejected(
        self, test_db_session, new_state, source
    ):
        player = await _player(test_db_session)
        with pytest.raises(ValueError):
            await apply_consent_signal(
                test_db_session,
                player.id,
                new_state,
                source,
                now=NOW,
            )


class TestDeniedDropsQueue:
    async def _outbox_states(
        self, session: AsyncSession, player_id: str
    ) -> list[tuple[str, str | None]]:
        rows = (
            await session.execute(
                select(BotOutbox.status, BotOutbox.drop_reason)
                .where(BotOutbox.player_id == player_id)
                .order_by(BotOutbox.id)
            )
        ).all()
        return [(r[0], r[1]) for r in rows]

    async def test_denied_drops_only_pending_notifications(
        self, test_db_session
    ):
        owner = await _player(test_db_session)
        other = await _player(test_db_session)
        await make_consent(test_db_session, owner, state="ALLOWED")
        await make_consent(test_db_session, other, state="ALLOWED")

        await make_outbox_row(test_db_session, owner)              # PENDING NOTIFICATION
        await make_outbox_row(
            test_db_session, owner, kind="REPLY", type_key="DIALOG",
            counts_toward_cap=False,
        )                                                          # PENDING REPLY
        await make_outbox_row(
            test_db_session, owner, status="SENT"
        )                                                          # SENT row
        await make_outbox_row(test_db_session, other)              # other player's

        await apply_consent_signal(
            test_db_session, owner.id, "DENIED", "VK_ERROR_901",
            now=NOW,
        )

        assert await self._outbox_states(test_db_session, owner.id) == [
            ("DROPPED", "BLOCKED"),
            ("PENDING", None),
            ("SENT", None),
        ]
        assert await self._outbox_states(
            test_db_session, other.id
        ) == [("PENDING", None)]

    async def test_denied_via_event_is_no_consent(
        self, test_db_session
    ):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        await make_outbox_row(test_db_session, player)

        await apply_consent_signal(
            test_db_session, player.id, "DENIED", "VK_EVENT", now=NOW
        )
        assert await self._outbox_states(
            test_db_session, player.id
        ) == [("DROPPED", "NO_CONSENT")]

    async def test_repeated_denied_still_drops(self, test_db_session):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="DENIED")
        await make_outbox_row(test_db_session, player)

        # Already DENIED — a repeat still sweeps new PENDING rows.
        await apply_consent_signal(
            test_db_session, player.id, "DENIED", "VK_EVENT", now=NOW
        )
        assert await self._outbox_states(
            test_db_session, player.id
        ) == [("DROPPED", "NO_CONSENT")]

    async def test_allowed_never_resurrects(self, test_db_session):
        player = await _player(test_db_session)
        await make_consent(test_db_session, player, state="ALLOWED")
        await make_outbox_row(test_db_session, player)
        await apply_consent_signal(
            test_db_session, player.id, "DENIED", "VK_EVENT", now=NOW
        )
        await apply_consent_signal(
            test_db_session, player.id, "ALLOWED", "VK_EVENT",
            now=NOW + timedelta(minutes=5),
        )
        assert await self._outbox_states(
            test_db_session, player.id
        ) == [("DROPPED", "NO_CONSENT")]


class TestRecordVkCheck:
    async def test_failed_check_changes_nothing(self, test_db_session):
        player = await _player(test_db_session)
        earlier = NOW - timedelta(hours=2)
        await make_consent(
            test_db_session, player, state="ALLOWED",
            state_changed_at=earlier, last_checked_at=earlier,
        )
        result = await record_vk_check(
            test_db_session, player.id, None, now=NOW
        )
        assert result is None
        consent = await get_or_create_consent(test_db_session, player.id)
        assert consent.state == "ALLOWED"
        assert _aware(consent.last_checked_at) == earlier

    async def test_check_false_denies_and_marks_check(
        self, test_db_session
    ):
        player = await _player(test_db_session)
        result = await record_vk_check(
            test_db_session, player.id, False, now=NOW
        )
        assert result.new == "DENIED"
        consent = await get_or_create_consent(test_db_session, player.id)
        assert consent.state_source == "VK_CHECK"
        assert _aware(consent.last_checked_at) == NOW

    async def test_check_true_allows(self, test_db_session):
        player = await _player(test_db_session)
        result = await record_vk_check(
            test_db_session, player.id, True, now=NOW
        )
        assert result.new == "ALLOWED"
        consent = await get_or_create_consent(test_db_session, player.id)
        assert consent.state == "ALLOWED"
        assert _aware(consent.last_checked_at) == NOW
