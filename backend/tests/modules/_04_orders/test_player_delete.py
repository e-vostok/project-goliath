"""
Player-delete hook tests of module 04_orders (admin test-player
cleanup, Spec 5.7+).

``orders_delete_player`` runs under the module advisory lock inside
``PlayerService.delete_player``'s transaction: orders where the target
judges without a verdict go back to the waiting queue (all five
assignment columns NULL — the all-or-none CHECK keeps holding), orders
the target authored are deleted, and decided orders they judged are
deleted too (the schema cannot keep a verdict without its judge).

Real DB, real module startup wiring (``orders_bot_started`` registers
the hook), real ``OrderService.run_retry_pass`` for the reassignment —
no mocks (Anti-Mock Guard).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.models import Nation
from modules._00_core.service import PlayerService
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import make_order
from tests.modules._04_orders.conftest import seed_author, seed_judge

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


async def _count(session: AsyncSession, *conditions) -> int:
    query = select(func.count()).select_from(Order)
    for condition in conditions:
        query = query.where(condition)
    return (await session.execute(query)).scalar_one()


class TestOrdersPlayerDeleteHook:
    """The module's player-delete hook semantics (Spec 5.7+)."""

    @pytest.mark.asyncio
    async def test_undecided_orders_requeue_and_worker_reassigns(
        self, session_factory, orders_bot_started
    ):
        """Deleting the judge returns their undecided orders to the
        queue — a real worker pass then assigns a new judge, so the
        author keeps a live order (Spec: judge reset)."""
        async with session_factory() as session:
            author, author_nation = await seed_author(session, 881001)
            target = await seed_judge(session, 881002, nation=True)
            replacement = await seed_judge(session, 881003, nation=True)
            order = await make_order(
                session,
                author,
                nation=author_nation,
                judge=target,
            )
            await session.commit()
            target_id = target.id
            order_id = order.id
            replacement_id = replacement.id

        async with session_factory() as session:
            async with session.begin():
                await PlayerService.delete_player(session, target_id)

        # Back in the queue: every assignment column is NULL — the row
        # is a clean SUBMITTED and all 8 CHECKs still hold.
        async with session_factory() as session:
            order = await session.get(Order, order_id)
            assert order is not None
            assert order.judge_player_id is None
            assert order.distributed_at is None
            assert order.deadline_at is None
            assert order.reminder_at is None
            assert order.reminder_sent_at is None

        # One real worker pass assigns the remaining candidate.
        stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.assigned == 1
        assert stats.errors == 0
        async with session_factory() as session:
            order = await session.get(Order, order_id)
            assert order.judge_player_id == replacement_id
            assert order.distributed_at is not None

    @pytest.mark.asyncio
    async def test_authored_and_decided_orders_are_deleted(
        self, session_factory, orders_bot_started
    ):
        """Orders the target authored disappear with their verdict
        columns; orders they judged with a verdict are deleted — a
        verdict cannot outlive its judge (ck_orders_verdict_needs_judge).
        Other players' orders are untouched."""
        async with session_factory() as session:
            author, author_nation = await seed_author(session, 882001)
            target = await seed_judge(session, 882002, nation=True)
            target_nation = (
                await session.execute(
                    select(Nation).where(Nation.owner_player_id == target.id)
                )
            ).scalar_one()
            authored = await make_order(session, target, nation=target_nation)
            authored_decided = await make_order(
                session,
                target,
                nation=target_nation,
                judge=author,
                submitted_at=datetime.now(UTC),
                verdict_at=datetime.now(UTC) + timedelta(hours=1),
            )
            judged_decided = await make_order(
                session,
                author,
                nation=author_nation,
                judge=target,
                submitted_at=datetime.now(UTC),
                verdict_at=datetime.now(UTC) + timedelta(hours=1),
            )
            keep = await make_order(session, author, nation=author_nation)
            await session.commit()
            target_id = target.id
            gone_ids = {authored.id, authored_decided.id, judged_decided.id}
            keep_id = keep.id

        async with session_factory() as session:
            async with session.begin():
                await PlayerService.delete_player(session, target_id)

        async with session_factory() as session:
            assert await _count(session, Order.id.in_(gone_ids)) == 0
            kept = await session.get(Order, keep_id)
            assert kept is not None
            assert kept.judge_player_id is None
