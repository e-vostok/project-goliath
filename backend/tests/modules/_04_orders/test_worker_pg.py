"""
PostgreSQL-only worker concurrency test of module 04_orders
(Spec 2.3; Appendix T «Конкурентность»).

Two ``run_retry_pass`` calls run on separate connections under
``asyncio.gather``. The module advisory lock serializes each
``distribute`` and the conditional ``UPDATE ... WHERE reminder_sent_at
IS NULL`` claims every reminder row exactly once — so two racing
passes assign each waiting order once and queue each reminder once.

Skipped unless ``DATABASE_URL_TEST`` names a ``*_test`` database (see
tests/fixtures/postgres.py).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from modules._02_bot.models import BotOutbox
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_consent,
    make_order,
)
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)

pytestmark = pytest.mark.postgres

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


async def _seed_player(session, vk_user_id: int):
    """A nation owner — a reachable judge, a valid order author."""
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


class TestConcurrentRetryPass:
    async def test_two_passes_assign_once_and_remind_once(
        self, pg_db, orders_bot_started
    ):
        async with pg_db() as session:
            judge = await _seed_player(session, 779901)
            await make_consent(session, judge, state="ALLOWED")
            author_a = await _seed_player(session, 779902)
            author_b = await _seed_player(session, 779903)
            waiting_a = await make_order(session, author_a)
            waiting_b = await make_order(session, author_b)
            # Distributed 60 h ago: its reminder went due 6 h ago.
            reminded = await make_order(
                session,
                author_a,
                judge=judge,
                submitted_at=NOW - timedelta(hours=60),
            )
            await session.commit()
            waiting_ids = {waiting_a.id, waiting_b.id}
            reminded_id = reminded.id

        stats_a, stats_b = await asyncio.gather(
            OrderService.run_retry_pass(pg_db, now=NOW),
            OrderService.run_retry_pass(pg_db, now=NOW),
        )

        # Every waiting order got its judge exactly once across the
        # two racing passes (any eligible player may have been picked —
        # never the author).
        assert stats_a.assigned + stats_b.assigned == 2
        async with pg_db() as session:
            for order_id in waiting_ids:
                order = (
                    await session.execute(select(Order).where(Order.id == order_id))
                ).scalar_one()
                assert order.judge_player_id is not None
                assert order.judge_player_id != order.author_player_id

            # Exactly one reminder message queued; the row is marked.
            rows = (
                (
                    await session.execute(
                        select(BotOutbox).where(
                            BotOutbox.type_key == "ORDER_JUDGE_REMINDER"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].event_key == f"order_reminder:{reminded_id}"
            order = (
                await session.execute(select(Order).where(Order.id == reminded_id))
            ).scalar_one()
            assert order.reminder_sent_at is not None
        assert stats_a.reminders_sent + stats_b.reminders_sent == 1
        assert stats_a.errors == 0
        assert stats_b.errors == 0
