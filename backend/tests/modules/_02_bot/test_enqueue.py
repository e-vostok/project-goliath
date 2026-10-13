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
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Nation, Player
from modules._02_bot.service import BotService, EnqueueResult
from modules._02_bot.models import BotOutbox
from tests.fixtures.factories import make_consent
from tests.fixtures.profile import VALID_PROFILE

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


async def _player(session: AsyncSession) -> Player:
    player = Player(
        id=str(uuid.uuid4()),
        vk_user_id=uuid.uuid4().int % 10**9,
        created_at=NOW,
    )
    session.add(player)
    await session.flush()
    return player


async def _member(
    session: AsyncSession, *, consent: str | None = "ALLOWED"
) -> Player:
    """A player with a nation row and the given consent state."""
    player = await _player(session)
    session.add(
        Nation(
            id=str(uuid.uuid4()),
            owner_player_id=player.id,
            name=f"N-{player.id[:8]}",
            color_hex="#" + uuid.uuid4().hex[:6].upper(),
            leader_name=VALID_PROFILE["leader_name"],
            leader_title=VALID_PROFILE["leader_title"],
            history_url=VALID_PROFILE["history_url"],
            created_at=NOW,
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
    "game_date": "0001-01-15",
    "nation_name": "N",
    "province_count": 3,
    "next_tick_time": "завтра",
}

_DIRECTIVE_VARS = {"directive_title": "Д-1", "status_text": "в работе"}


class TestQueued:
    async def test_queued_row_fields(
        self, test_db_session, bot_started
    ):
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
        assert _aware(row.expires_at) == event_at + timedelta(
            minutes=360
        )
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

    async def test_disabled_type_skipped(
        self, test_db_session, bot_started
    ):
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
            ("GHOST_TYPE", {}),                          # unregistered
            ("TICK_DIGEST", {"turn": 7}),                # missing vars
            (
                "TICK_DIGEST",
                _DIGEST_VARS | {"extra": "x"},
            ),                                         # surplus var
            (
                "TICK_DIGEST",
                _DIGEST_VARS | {"turn": True},
            ),                                         # bool is rejected
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
