"""
Judge-rating service tests (0.14.0 unit 6a).

``change_judge_rating`` is the single write path to
``players.judge_rating``: every call journals the clamp, a repeated
``source_key`` is a no-op, and the argument rules split MANUAL (note +
actor required) from the ORDER_* penalties (both forbidden).

Honest in-memory database, factories from tests/fixtures — no mocks
(Anti-Mock Guard). Each test runs inside ``test_db_session``'s rolled-
back transaction; the service's own SAVEPOINT still applies.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from modules._00_core.exceptions import (
    PlayerNotFoundError,
    RatingChangeInvalidError,
)
from modules._00_core.models import JudgeRatingLog, Player
from modules._00_core.rating_service import (
    change_judge_rating,
    list_judge_rating_log,
)
from tests.fixtures.factories import PlayerFactory


_vk_seq = iter(range(42424400, 42424900))


async def _player(session, rating: int = 0) -> Player:
    player = PlayerFactory.build(
        vk_user_id=next(_vk_seq), nations=[], judge_rating=rating
    )
    session.add(player)
    await session.flush()
    return player


async def _rating(session, player_id: str) -> int:
    return (
        await session.execute(
            select(Player.judge_rating).where(Player.id == player_id)
        )
    ).scalar_one()


async def _log_count(session, player_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(JudgeRatingLog)
            .where(JudgeRatingLog.player_id == player_id)
        )
    ).scalar_one()


class TestChangeJudgeRating:
    """The write path: clamp, journal, idempotency."""

    async def test_order_refused_minus_two_from_zero(self, test_db_session):
        player = await _player(test_db_session)

        result = await change_judge_rating(
            test_db_session,
            player.id,
            delta=-2,
            reason_code="ORDER_REFUSED",
            source_key="order:10:refused",
        )

        assert result.created is True
        assert (result.rating_before, result.rating_after) == (0, -2)
        assert result.applied_delta == -2
        assert await _rating(test_db_session, player.id) == -2

        row = (
            await test_db_session.execute(
                select(JudgeRatingLog).where(JudgeRatingLog.id == result.entry_id)
            )
        ).scalar_one()
        assert (row.player_id, row.delta, row.applied_delta) == (
            player.id,
            -2,
            -2,
        )
        assert (row.rating_before, row.rating_after) == (0, -2)
        assert row.reason_code == "ORDER_REFUSED"
        assert row.source_key == "order:10:refused"
        assert row.note is None and row.actor_player_id is None
        assert row.created_at is not None

    async def test_clamp_at_minimum_keeps_requested_delta(self, test_db_session):
        """−5 against −99 applies only −1; the journal stores both."""
        player = await _player(test_db_session, rating=-99)

        result = await change_judge_rating(
            test_db_session,
            player.id,
            delta=-5,
            reason_code="ORDER_OVERDUE",
            source_key="order:11:overdue",
        )

        assert (result.rating_before, result.rating_after) == (-99, -100)
        assert result.applied_delta == -1
        assert await _rating(test_db_session, player.id) == -100
        row = (
            await test_db_session.execute(
                select(JudgeRatingLog).where(JudgeRatingLog.id == result.entry_id)
            )
        ).scalar_one()
        assert (row.delta, row.applied_delta) == (-5, -1)

    async def test_manual_clamps_at_maximum(self, test_db_session):
        player = await _player(test_db_session, rating=90)
        actor = await _player(test_db_session)

        result = await change_judge_rating(
            test_db_session,
            player.id,
            delta=50,
            reason_code="MANUAL",
            source_key="admin:fix:1",
            note="  исправление ошибки  ",
            actor_player_id=actor.id,
        )

        assert (result.rating_before, result.rating_after) == (90, 100)
        assert result.applied_delta == 10
        row = (
            await test_db_session.execute(
                select(JudgeRatingLog).where(JudgeRatingLog.id == result.entry_id)
            )
        ).scalar_one()
        assert row.reason_code == "MANUAL"
        assert row.note == "исправление ошибки"
        assert row.actor_player_id == actor.id

    async def test_same_source_key_never_moves_twice(self, test_db_session):
        player = await _player(test_db_session)

        first = await change_judge_rating(
            test_db_session,
            player.id,
            delta=-2,
            reason_code="ORDER_REFUSED",
            source_key="order:10:refused",
        )
        second = await change_judge_rating(
            test_db_session,
            player.id,
            delta=-2,
            reason_code="ORDER_REFUSED",
            source_key="order:10:refused",
        )

        assert first.created is True and second.created is False
        assert second.entry_id == first.entry_id
        assert (second.rating_before, second.rating_after) == (0, -2)
        assert await _rating(test_db_session, player.id) == -2
        assert await _log_count(test_db_session, player.id) == 1


class TestArgumentRules:
    """Every rejected shape raises RatingChangeInvalidError."""

    async def test_manual_requires_note_and_actor(self, test_db_session):
        player = await _player(test_db_session)
        for kwargs in (
            {"note": None, "actor_player_id": player.id},
            {"note": "   ", "actor_player_id": player.id},
            {"note": "причина", "actor_player_id": None},
        ):
            with pytest.raises(RatingChangeInvalidError):
                await change_judge_rating(
                    test_db_session,
                    player.id,
                    delta=1,
                    reason_code="MANUAL",
                    source_key="admin:fix:bad",
                    **kwargs,
                )
        assert await _log_count(test_db_session, player.id) == 0

    async def test_order_reasons_forbid_note_and_actor(self, test_db_session):
        player = await _player(test_db_session)
        for kwargs in (
            {"note": "причина"},
            {"actor_player_id": player.id},
        ):
            with pytest.raises(RatingChangeInvalidError):
                await change_judge_rating(
                    test_db_session,
                    player.id,
                    delta=-2,
                    reason_code="ORDER_REFUSED",
                    source_key="order:10:refused",
                    **kwargs,
                )

    async def test_zero_delta_rejected(self, test_db_session):
        player = await _player(test_db_session)
        with pytest.raises(RatingChangeInvalidError):
            await change_judge_rating(
                test_db_session,
                player.id,
                delta=0,
                reason_code="ORDER_REFUSED",
                source_key="order:10:refused",
            )

    async def test_unknown_player_raises_not_found(self, test_db_session):
        with pytest.raises(PlayerNotFoundError):
            await change_judge_rating(
                test_db_session,
                "no-such-player",
                delta=-2,
                reason_code="ORDER_REFUSED",
                source_key="order:10:refused",
            )


class TestListJudgeRatingLog:
    """Newest-first journal pages for the admin panel."""

    async def test_newest_first_and_paged_by_before_id(self, test_db_session):
        player = await _player(test_db_session)
        for turn in (1, 2, 3):
            await change_judge_rating(
                test_db_session,
                player.id,
                delta=-turn,
                reason_code="ORDER_REFUSED",
                source_key=f"order:{turn}:refused",
            )

        first_page = await list_judge_rating_log(
            test_db_session, player.id, limit=2
        )
        assert [entry.delta for entry in first_page] == [-3, -2]
        assert all(
            isinstance(entry.created_at, type(first_page[0].created_at))
            for entry in first_page
        )

        second_page = await list_judge_rating_log(
            test_db_session,
            player.id,
            limit=2,
            before_id=first_page[-1].id,
        )
        assert [entry.delta for entry in second_page] == [-1]

        # The journal carries every column.
        entry = second_page[0]
        assert (entry.player_id, entry.reason_code) == (
            player.id,
            "ORDER_REFUSED",
        )
        assert (entry.rating_before, entry.rating_after) == (0, -1)

    async def test_other_players_journal_is_not_listed(self, test_db_session):
        player = await _player(test_db_session)
        other = await _player(test_db_session)
        await change_judge_rating(
            test_db_session,
            other.id,
            delta=-2,
            reason_code="ORDER_REFUSED",
            source_key="order:9:refused",
        )
        assert (
            await list_judge_rating_log(test_db_session, player.id, limit=10)
            == []
        )
