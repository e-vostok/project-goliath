"""
PostgreSQL-only concurrency tests of module 04_orders (Spec 5.1, 3.5;
Appendix T «Конкурентность»).

Real migrated schema, real ``pg_advisory_xact_lock`` — two submissions
run on separate connections under ``asyncio.gather``; nothing is mocked.
The module advisory lock must serialize the author-limit count and the
public-number assignment.

Skipped unless ``DATABASE_URL_TEST`` names a ``*_test`` database (see
tests/fixtures/postgres.py).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from modules._00_core.models import Player
from modules._04_orders.exceptions import OrderAuthorLimitReachedError
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_order,
)
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)

pytestmark = pytest.mark.postgres

_VALID = {
    "title": "Приказ о марш-броске",
    "summary": "Соединить группировки к полуночи.",
    "article_url": "https://vk.com/@march-order",
}


async def _submit_and_commit(session_maker, player_id: str) -> int:
    """One submit on its own connection, committed — the request path."""
    async with session_maker() as session:
        outcome = await OrderService.submit(
            session,
            player_id=player_id,
            client_request_id=str(uuid.uuid4()),
            **_VALID,
        )
        await session.commit()
        return outcome.view.number


async def _seed_author(session, vk_user_id: int) -> Player:
    player = PlayerFactory.build(vk_user_id=vk_user_id, nations=[])
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


class TestConcurrentSubmit:
    async def test_same_author_one_free_slot_creates_one_order(
        self, pg_db, orders_started
    ):
        """INV-O15 under the advisory lock: with a single free slot two
        concurrent submissions of one author create exactly one order;
        the loser gets ORDER_AUTHOR_LIMIT_REACHED."""
        async with pg_db() as session:
            author = await _seed_author(session, 770501)
            limit = orders_started.author.max_unresolved_orders
            for _ in range(limit - 1):
                await make_order(session, author)
            await session.commit()
            author_id = author.id

        results = await asyncio.gather(
            _submit_and_commit(pg_db, author_id),
            _submit_and_commit(pg_db, author_id),
            return_exceptions=True,
        )

        numbers = [r for r in results if isinstance(r, int)]
        failures = [
            r for r in results
            if isinstance(r, OrderAuthorLimitReachedError)
        ]
        assert len(numbers) == 1, f"expected one order, got {results!r}"
        assert len(failures) == 1, f"expected one refusal, got {results!r}"

        async with pg_db() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.author_player_id == author_id)
            )
            assert count == limit

    async def test_concurrent_submissions_get_distinct_numbers(
        self, pg_db, orders_started
    ):
        """Spec 3.5: two simultaneous submissions never share a number."""
        async with pg_db() as session:
            author_a = await _seed_author(session, 770511)
            author_b = await _seed_author(session, 770512)
            await session.commit()
            ids = (author_a.id, author_b.id)

        first, second = await asyncio.gather(
            _submit_and_commit(pg_db, ids[0]),
            _submit_and_commit(pg_db, ids[1]),
        )

        assert {first, second} == {1, 2}
        async with pg_db() as session:
            rows = (
                await session.execute(
                    select(Order.number).order_by(Order.number)
                )
            ).scalars().all()
            assert list(rows) == [1, 2]
