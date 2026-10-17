"""
PostgreSQL-only verdict concurrency test (Spec 5.1, INV-O1;
Appendix T «Конкурентность»).

Two verdict writes by the same judge run on separate connections
under ``asyncio.gather``. The module advisory lock serializes them —
the loser's re-read sees the committed verdict and answers
``ORDER_VERDICT_EXISTS``; exactly one verdict lands.

Skipped unless ``DATABASE_URL_TEST`` names a ``*_test`` database (see
tests/fixtures/postgres.py).
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from modules._04_orders.exceptions import OrderVerdictExistsError
from modules._04_orders.models import Order
from modules._04_orders.service import OrderDetailView, OrderService
from tests.fixtures.factories import make_order
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.modules._04_orders.test_submission_pg import _seed_author

pytestmark = pytest.mark.postgres

_VERDICTS = (
    {
        "title": "Первый вердикт",
        "summary": "Суть первого вердикта.",
        "article_url": "https://vk.com/@verdict-a",
    },
    {
        "title": "Второй вердикт",
        "summary": "Суть второго вердикта.",
        "article_url": "https://vk.com/@verdict-b",
    },
)


async def _verdict_and_commit(
    session_maker, player_id: str, number: int, fields: dict
) -> OrderDetailView:
    """One verdict write on its own connection, committed — the
    request path."""
    async with session_maker() as session:
        view = await OrderService.write_verdict(
            session, player_id=player_id, number=number, **fields
        )
        await session.commit()
        return view


class TestConcurrentVerdict:
    async def test_two_concurrent_verdicts_land_exactly_once(
        self, pg_db, orders_started
    ):
        """INV-O1 under the advisory lock: two simultaneous verdicts
        by the assigned judge — exactly one is written, the loser gets
        ORDER_VERDICT_EXISTS."""
        async with pg_db() as session:
            author = await _seed_author(session, 774001)
            judge = await _seed_author(session, 774002)
            order = await make_order(session, author, judge=judge)
            await session.commit()
            judge_id, number = judge.id, order.number

        results = await asyncio.gather(
            _verdict_and_commit(pg_db, judge_id, number, _VERDICTS[0]),
            _verdict_and_commit(pg_db, judge_id, number, _VERDICTS[1]),
            return_exceptions=True,
        )

        wins = [
            r for r in results if isinstance(r, OrderDetailView)
        ]
        losses = [
            r for r in results
            if isinstance(r, OrderVerdictExistsError)
        ]
        assert len(wins) == 1, f"expected one verdict, got {results!r}"
        assert len(losses) == 1, (
            f"expected one ORDER_VERDICT_EXISTS, got {results!r}"
        )

        async with pg_db() as session:
            row = (
                await session.execute(select(Order))
            ).scalar_one()
            assert row.verdict_at is not None
            assert row.verdict_title in {
                verdict["title"] for verdict in _VERDICTS
            }
