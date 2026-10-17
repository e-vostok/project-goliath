"""
PostgreSQL end-to-end test of module 04_orders (Spec 2.3, 5.1;
Appendix T «Сквозной тест») — Issue 10.

The same chain as test_integration.py, on the real migrated schema:
HTTP requests run on per-request sessions of an app-independent
asyncpg engine (``pg_db``), the worker pass runs with a fixed ``now``
between requests. Real ``pg_advisory_xact_lock`` paths inside
``submit``/``distribute``/``write_verdict`` are exercised for real.

Skipped unless ``DATABASE_URL_TEST`` names a ``*_test`` database (see
tests/fixtures/postgres.py).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from core.db import get_session
from main import app
from modules._02_bot.models import BotOutbox
from modules._03_registry.startup import startup_registry
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService, RetryPassStats
from tests.fixtures.factories import make_consent
from tests.fixtures.postgres import (
    pg_clean,  # noqa: F401 — autouse per-test data reset
    pg_db,
    pg_schema,  # noqa: F401 — resolved through the fixture chain
    pg_url,  # noqa: F401 — resolved through the fixture chain
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge
from tests.modules._04_orders.test_integration import (
    ORDERS_URL,
    REGISTRY_ORDERS_URL,
    VALID_ORDER,
    VALID_VERDICT,
)

pytestmark = pytest.mark.postgres

DEADLINE_HOURS = 72  # judge.verdict_deadline_hours in configs/04_orders.yaml
REMINDER_HOURS = 54  # deadline * reminder_percent 75 (integer seconds)


@pytest_asyncio.fixture
async def orders_client(pg_db):
    """HTTP client where every request opens its own session on the
    ``pg_db`` engine — same shape as the SQLite integration client."""

    async def _override_get_session():
        async with pg_db() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _order_row(session, number: int = 1) -> Order:
    return (
        await session.execute(select(Order).where(Order.number == number))
    ).scalar_one()


async def _outbox_by_type(session) -> dict[str, BotOutbox]:
    rows = (await session.execute(select(BotOutbox))).scalars().all()
    return {row.type_key: row for row in rows}


class TestEndToEndPg:
    """The whole chain against the migrated PostgreSQL schema."""

    async def test_full_order_cycle(self, orders_client, pg_db, orders_bot_started):
        async with pg_db() as session:
            author, nation = await seed_author(
                session, 881501, nation_name="Северная Лига"
            )
            await make_consent(session, author, state="ALLOWED")
            await session.commit()
            author_id = author.id

        request_id = str(uuid.uuid4())
        author_headers = bearer_headers(author_id)
        bodies: list[str] = []

        submit = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": request_id},
            headers=author_headers,
        )
        assert submit.status_code == 201
        bodies.append(submit.text)
        body = submit.json()
        assert body["number"] == 1
        assert body["distributed"] is False

        async with pg_db() as session:
            judge = await seed_judge(session, 881502, nation=True, consent="ALLOWED")
            await session.commit()
            judge_id, judge_vk = judge.id, judge.vk_user_id

        # One wall-clock tick past the submit so the stage stamps order
        # strictly even on coarse-grained clocks.
        await asyncio.sleep(0.02)
        t_assign = datetime.now(timezone.utc)
        stats = await OrderService.run_retry_pass(pg_db, now=t_assign)
        assert stats == RetryPassStats(assigned=1)

        async with pg_db() as session:
            order = await _order_row(session)
            assert order.judge_player_id == judge_id
            assert order.distributed_at == t_assign
            assert order.deadline_at == t_assign + timedelta(hours=DEADLINE_HOURS)
            assert order.reminder_at == t_assign + timedelta(hours=REMINDER_HOURS)
            outbox = await _outbox_by_type(session)
        assert outbox["ORDER_JUDGE_ASSIGNED"].player_id == judge_id
        assert outbox["ORDER_DISTRIBUTED"].player_id == author_id

        judge_headers = bearer_headers(judge_id)
        queue = await orders_client.get(f"{ORDERS_URL}/assigned", headers=judge_headers)
        bodies.append(queue.text)
        assert [item["number"] for item in queue.json()["items"]] == [1]

        stats = await OrderService.run_retry_pass(
            pg_db, now=t_assign + timedelta(hours=55)
        )
        assert stats.reminders_sent == 1
        assert stats.errors == 0
        async with pg_db() as session:
            reminders = (
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
        assert len(reminders) == 1
        assert reminders[0].player_id == judge_id
        assert reminders[0].payload["hours_left"] == 17

        verdict = await orders_client.post(
            f"{ORDERS_URL}/1/verdict",
            json=VALID_VERDICT,
            headers=judge_headers,
        )
        assert verdict.status_code == 201
        bodies.append(verdict.text)
        assert verdict.json()["verdict"] == VALID_VERDICT

        async with pg_db() as session:
            outbox = await _outbox_by_type(session)
            assert outbox["ORDER_VERDICT_READY"].player_id == author_id

        startup_registry()
        table = await orders_client.get(REGISTRY_ORDERS_URL, headers=author_headers)
        assert table.status_code == 200
        bodies.append(table.text)
        cells = table.json()["rows"][0]["cells"]
        keys = [
            cells[stage]["key"] for stage in ("submitted", "distributed", "verdict")
        ]
        assert all(key is not None for key in keys)
        assert keys[0] <= keys[1] <= keys[2]

        # The stored row carries the three stages strictly in order
        # (Registry cell keys resolve to whole seconds).
        async with pg_db() as session:
            order = await _order_row(session)
            assert order.submitted_at < order.distributed_at < order.verdict_at

        # INV-O5: no response body carries the judge's ids.
        for text in bodies:
            assert judge_id not in text
            assert str(judge_vk) not in text

        # INV-O9: the idempotent repeat creates nothing new.
        repeat = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": request_id},
            headers=author_headers,
        )
        assert repeat.status_code == 200
        bodies.append(repeat.text)
        assert repeat.json()["number"] == 1
        async with pg_db() as session:
            count = await session.scalar(select(func.count()).select_from(Order))
            assert count == 1
        for text in bodies[-1:]:
            assert judge_id not in text
            assert str(judge_vk) not in text

    async def test_waiting_order_gets_judge_once_candidate_exists(
        self, orders_client, pg_db, orders_bot_started
    ):
        """No candidate at submit: the order waits; once a reachable
        player appears, the next pass assigns it (Spec 2.3)."""
        async with pg_db() as session:
            author, _ = await seed_author(session, 881601)
            await session.commit()
            author_id = author.id

        submit = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": str(uuid.uuid4())},
            headers=bearer_headers(author_id),
        )
        assert submit.status_code == 201
        assert submit.json()["distributed"] is False

        stats = await OrderService.run_retry_pass(pg_db, now=datetime.now(timezone.utc))
        assert stats.assigned == 0
        assert stats.still_waiting == 1
        async with pg_db() as session:
            assert (await _order_row(session)).judge_player_id is None

        async with pg_db() as session:
            judge = await seed_judge(session, 881602, nation=True)
            await session.commit()
            judge_id = judge.id

        stats = await OrderService.run_retry_pass(pg_db, now=datetime.now(timezone.utc))
        assert stats.assigned == 1
        assert stats.errors == 0
        async with pg_db() as session:
            assert (await _order_row(session)).judge_player_id == judge_id
