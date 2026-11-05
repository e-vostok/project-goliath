"""
Judge-rating concurrency on real PostgreSQL (0.14.0 unit 6a).

The guarantees SQLite cannot express: two concurrent sessions carrying
the SAME ``source_key`` produce exactly one journal row (the row lock
serialises them and the loser re-reads the winner's entry), and two
sessions with different keys both apply their deltas — the
``SELECT ... FOR UPDATE`` on the player row means no change is lost.

Requires DATABASE_URL_TEST; ``pg_db`` gives independent asyncpg
sessions on the migrated, wiped *_test database (Anti-Mock Guard).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from modules._00_core.models import JudgeRatingLog, Player
from modules._00_core.rating_service import change_judge_rating
from tests.fixtures.factories import PlayerFactory
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,  # noqa: F401 — resolved through the fixture chain
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)

pytestmark = pytest.mark.postgres


async def _make_player(pg_db, vk_user_id: int) -> str:
    async with pg_db() as session:
        player = PlayerFactory.build(vk_user_id=vk_user_id, nations=[])
        session.add(player)
        await session.commit()
        return player.id


async def _apply(pg_db, player_id: str, delta: int, key: str):
    """One independent session/transaction around one rating change."""
    async with pg_db() as session:
        async with session.begin():
            return await change_judge_rating(
                session,
                player_id,
                delta=delta,
                reason_code="ORDER_REFUSED",
                source_key=key,
            )


async def _state(pg_db, player_id: str) -> tuple[int, int]:
    """(rating, journal row count) seen from a fresh session."""
    async with pg_db() as session:
        rating = (
            await session.execute(
                select(Player.judge_rating).where(Player.id == player_id)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(func.count())
                .select_from(JudgeRatingLog)
                .where(JudgeRatingLog.player_id == player_id)
            )
        ).scalar_one()
        return rating, rows


async def test_concurrent_same_source_key_writes_one_row(pg_db):
    player_id = await _make_player(pg_db, 42424330)

    first, second = await asyncio.gather(
        _apply(pg_db, player_id, -2, "order:10:refused"),
        _apply(pg_db, player_id, -2, "order:10:refused"),
    )

    # Exactly one of them created the entry; the repeat returned it.
    assert {first.created, second.created} == {True, False}
    assert first.entry_id == second.entry_id
    assert await _state(pg_db, player_id) == (-2, 1)


async def test_concurrent_different_keys_apply_both(pg_db):
    player_id = await _make_player(pg_db, 42424331)

    first, second = await asyncio.gather(
        _apply(pg_db, player_id, -2, "order:10:refused"),
        _apply(pg_db, player_id, -3, "order:11:refused"),
    )

    assert first.created and second.created
    rating, rows = await _state(pg_db, player_id)
    assert rating == -5
    assert rows == 2
