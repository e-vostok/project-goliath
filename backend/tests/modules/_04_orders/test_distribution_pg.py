"""
PostgreSQL-only distribution concurrency test (Spec 3.3, INV-O1;
Appendix T «Конкурентность»).

Two submissions run on separate connections under ``asyncio.gather``.
With a single free slot in the one eligible judge's load, the module
advisory lock must serialize the two attempts so the slot is taken
exactly once — never twice (the judge's limit is a hard invariant).

Skipped unless ``DATABASE_URL_TEST`` names a ``*_test`` database (see
tests/fixtures/postgres.py).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from modules._00_core.models import Player
from modules._04_orders.models import Order
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_order,
)
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset,
    pg_db,  # noqa: F401 — resolved through the fixture chain
    pg_schema,  # noqa: F401 — resolved through the fixture chain,
    pg_url,  # noqa: F401 — resolved through the fixture chain,
)
from tests.modules._04_orders.test_submission_pg import (
    _submit_and_commit,
)

pytestmark = pytest.mark.postgres


async def _seed_player(session, vk_user_id: int, *, judge_rating: int) -> Player:
    """A nation owner with a chosen judge rating (below 0 keeps them
    out of the candidate set under the real config's min_rating = 0)."""
    player = PlayerFactory.build(
        vk_user_id=vk_user_id,
        judge_rating=judge_rating,
        nations=[],
    )
    session.add(player)
    await session.flush()
    session.add(
        NationFactory.build(
            owner=player,
            name=f"Государство {vk_user_id}",
            color_hex=f"#{vk_user_id % 0xFFFFFF:06X}",
            provinces=[],
            scheduled_actions=[],
        )
    )
    await session.flush()
    return player


class TestConcurrentDistribute:
    async def test_one_free_slot_is_taken_once(self, pg_db, orders_started):
        """Two concurrent submissions, one free judge-load slot: the
        advisory lock serializes them, the conditional UPDATE guards
        the row — exactly one order claims the last slot."""
        max_pending = orders_started.judge.max_pending_verdicts
        async with pg_db() as session:
            judge = await _seed_player(session, 772001, judge_rating=0)
            filler = await _seed_player(session, 772002, judge_rating=-1)
            author_a = await _seed_player(session, 772003, judge_rating=-1)
            author_b = await _seed_player(session, 772004, judge_rating=-1)
            # One free slot: the only eligible judge is one pending
            # verdict below the limit.
            for _ in range(max_pending - 1):
                await make_order(session, filler, judge=judge)
            await session.commit()
            author_ids = (author_a.id, author_b.id)
            judge_id = judge.id

        numbers = await asyncio.gather(
            _submit_and_commit(pg_db, author_ids[0]),
            _submit_and_commit(pg_db, author_ids[1]),
        )
        assert sorted(numbers) == [1 + max_pending - 1, 2 + max_pending - 1]

        async with pg_db() as session:
            new_orders = (
                (
                    await session.execute(
                        select(Order).where(Order.author_player_id.in_(author_ids))
                    )
                )
                .scalars()
                .all()
            )
            assigned_to_judge = [o for o in new_orders if o.judge_player_id == judge_id]
            # The free slot went to exactly one of the two orders.
            assert len(assigned_to_judge) == 1
            # ...and the judge's pending count reached, never crossed,
            # the limit (Spec 3.2).
            pending = await session.scalar(
                select(func.count())
                .select_from(Order)
                .where(
                    Order.judge_player_id == judge_id,
                    Order.verdict_at.is_(None),
                )
            )
            assert pending == max_pending
