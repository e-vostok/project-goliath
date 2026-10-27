"""
End-to-end tests of module 04_orders (Spec 2.3, 5.1; Appendix T
«Сквозной тест») — Issue 10.

The whole chain on the real in-memory DB (Anti-Mock Guard — nothing at
the DB boundary is mocked): the author submits through the HTTP
client, the worker pass (``run_retry_pass`` called directly with a
fixed ``now``) assigns the judge and queues the notification pair, the
reminder pass queues one ``ORDER_JUDGE_REMINDER``, the judge writes
the verdict over HTTP and the author's ``ORDER_VERDICT_READY`` lands —
then the Registry source shows all three stages.

HTTP requests run on per-request sessions over the same engine (the
shared ``:memory:`` pool serialises everything on one connection), so
the test never holds ``test_db_session`` open while a pass runs.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from core.db import get_session
from main import app
from modules._02_bot.models import BotOutbox
from modules._03_registry.startup import startup_registry
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService, RetryPassStats
from tests.fixtures.factories import make_consent, make_order
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

ORDERS_URL = "/api/v1/orders"
REGISTRY_ORDERS_URL = "/api/v1/registry/tables/orders"

VALID_ORDER = {
    "title": "Приказ о наступлении",
    "summary": "Перейти в наступление на рассвете следующего дня.",
    "article_url": "https://vk.com/@attack-order",
}
VALID_VERDICT = {
    "title": "Вердикт по приказу",
    "summary": "Приказ рассмотрен и принят к исполнению.",
    "article_url": "https://vk.com/@verdict-one",
}

DEADLINE_HOURS = 72  # judge.verdict_deadline_hours in configs/04_orders.yaml
REMINDER_HOURS = 54  # deadline * reminder_percent 75 (integer seconds)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@pytest_asyncio.fixture
async def orders_client(session_factory):
    """
    HTTP client where every request opens its own session on the test
    engine — the production shape. The worker pass opens sibling
    sessions on the same shared connection, so ``test_db_session`` must
    not stay open while a pass runs (see test_worker.py).
    """

    async def _override_get_session():
        async with session_factory() as session:
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


class TestEndToEnd:
    """Appendix T «Сквозной тест»: submit -> distribute -> notifications
    -> reminder -> verdict -> announcement -> three Registry stages."""

    async def test_full_order_cycle(
        self, orders_client, session_factory, orders_bot_started
    ):
        # A player with a nation consents to bot messages; no second
        # player exists yet, so the order starts judge-less.
        async with session_factory() as session:
            author, nation = await seed_author(
                session, 881001, nation_name="Северная Лига"
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
        assert body["nation"] == {
            "name": "Северная Лига",
            "color": nation.color_hex,
            "short_name": nation.short_name,
            "flag_url": None,
        }

        # The second eligible player appears; the worker pass called
        # with a fixed now assigns the judge.
        async with session_factory() as session:
            judge = await seed_judge(session, 881002, nation=True, consent="ALLOWED")
            await session.commit()
            judge_id, judge_vk = judge.id, judge.vk_user_id

        # One wall-clock tick past the submit so the stage stamps order
        # strictly even on coarse-grained clocks.
        await asyncio.sleep(0.02)
        t_assign = datetime.now(UTC)
        stats = await OrderService.run_retry_pass(session_factory, now=t_assign)
        assert stats == RetryPassStats(assigned=1)

        async with session_factory() as session:
            order = await _order_row(session)
            assert order.judge_player_id == judge_id
            assert _aware(order.distributed_at) == t_assign
            assert _aware(order.deadline_at) == t_assign + timedelta(
                hours=DEADLINE_HOURS
            )
            assert _aware(order.reminder_at) == t_assign + timedelta(
                hours=REMINDER_HOURS
            )
            outbox = await _outbox_by_type(session)
        assert outbox["ORDER_JUDGE_ASSIGNED"].player_id == judge_id
        assert outbox["ORDER_DISTRIBUTED"].player_id == author_id

        judge_headers = bearer_headers(judge_id)
        detail = await orders_client.get(f"{ORDERS_URL}/1", headers=author_headers)
        bodies.append(detail.text)
        assert detail.json()["distributed"] is True
        assert detail.json()["can_write_verdict"] is False

        queue = await orders_client.get(f"{ORDERS_URL}/assigned", headers=judge_headers)
        bodies.append(queue.text)
        items = queue.json()["items"]
        assert len(items) == 1
        assert items[0]["number"] == 1

        detail_judge = await orders_client.get(f"{ORDERS_URL}/1", headers=judge_headers)
        bodies.append(detail_judge.text)
        assert detail_judge.json()["can_write_verdict"] is True

        # The reminder pass (now = +55 h, before the +72 h deadline)
        # queues exactly one ORDER_JUDGE_REMINDER to the judge.
        stats = await OrderService.run_retry_pass(
            session_factory, now=t_assign + timedelta(hours=55)
        )
        assert stats.reminders_sent == 1
        assert stats.errors == 0
        async with session_factory() as session:
            reminder = (
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
        assert len(reminder) == 1
        assert reminder[0].player_id == judge_id
        assert reminder[0].payload["hours_left"] == 17

        # The judge writes the verdict over HTTP.
        verdict = await orders_client.post(
            f"{ORDERS_URL}/1/verdict",
            json=VALID_VERDICT,
            headers=judge_headers,
        )
        assert verdict.status_code == 201
        bodies.append(verdict.text)
        assert verdict.json()["verdict"] == VALID_VERDICT
        assert verdict.json()["can_write_verdict"] is False

        # The author's ORDER_VERDICT_READY landed in the outbox.
        async with session_factory() as session:
            outbox = await _outbox_by_type(session)
            assert outbox["ORDER_VERDICT_READY"].player_id == author_id

        # The Registry source shows the three stages in order.
        startup_registry()
        table = await orders_client.get(REGISTRY_ORDERS_URL, headers=author_headers)
        assert table.status_code == 200
        bodies.append(table.text)
        rows = table.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["key"] == "o1"
        cells = rows[0]["cells"]
        keys = [
            cells[stage]["key"] for stage in ("submitted", "distributed", "verdict")
        ]
        assert all(key is not None for key in keys)
        assert keys[0] <= keys[1] <= keys[2]

        # The stored row carries the three stages strictly in order
        # (Registry cell keys resolve to whole seconds).
        async with session_factory() as session:
            order = await _order_row(session)
            assert (
                _aware(order.submitted_at)
                < _aware(order.distributed_at)
                < _aware(order.verdict_at)
            )

        # INV-O5: no response body anywhere in the chain carries the
        # judge's player id or VK id.
        for text in bodies:
            assert judge_id not in text
            assert str(judge_vk) not in text

        # INV-O9: a repeat with the same client_request_id creates
        # nothing new.
        repeat = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": request_id},
            headers=author_headers,
        )
        assert repeat.status_code == 200
        bodies.append(repeat.text)
        assert repeat.json()["number"] == 1
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(Order))
            assert count == 1

        for text in bodies[-1:]:
            assert judge_id not in text
            assert str(judge_vk) not in text

    async def test_waiting_order_gets_judge_once_candidate_exists(
        self, orders_client, session_factory, orders_bot_started
    ):
        """No candidate at submit: the order waits; once a reachable
        player appears, the next pass assigns it (Spec 2.3)."""
        async with session_factory() as session:
            author, _ = await seed_author(session, 881101)
            await session.commit()
            author_id = author.id

        submit = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": str(uuid.uuid4())},
            headers=bearer_headers(author_id),
        )
        assert submit.status_code == 201
        assert submit.json()["distributed"] is False

        stats = await OrderService.run_retry_pass(
            session_factory, now=datetime.now(UTC)
        )
        assert stats.assigned == 0
        assert stats.still_waiting == 1
        async with session_factory() as session:
            assert (await _order_row(session)).judge_player_id is None

        async with session_factory() as session:
            judge = await seed_judge(session, 881102, nation=True)
            await session.commit()
            judge_id = judge.id

        stats = await OrderService.run_retry_pass(
            session_factory, now=datetime.now(UTC)
        )
        assert stats.assigned == 1
        assert stats.errors == 0
        async with session_factory() as session:
            assert (await _order_row(session)).judge_player_id == judge_id


class TestReminderRace:
    """The claim UPDATE also guards the verdict column (Issue 10)."""

    async def test_verdict_written_after_read_skips_reminder(
        self, session_factory, orders_bot_started, monkeypatch
    ):
        """A verdict committed between the pass's candidate read and
        the row claim yields rowcount 0 — no reminder is queued and the
        pass counts it as skipped."""
        now = datetime.now(UTC)
        async with session_factory() as session:
            author, nation = await seed_author(session, 881201)
            judge = await seed_judge(session, 881202, nation=True, consent="ALLOWED")
            await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=now - timedelta(hours=60),
            )
            await session.commit()
            judge_id = judge.id

        real_remind = OrderService._remind_guarded

        async def remind_after_verdict(session, order, *, now):
            # The judge's verdict lands in the window between the
            # pass's candidate read and this row's claim.
            await OrderService.write_verdict(
                session,
                player_id=judge_id,
                number=order.number,
                **VALID_VERDICT,
            )
            return await real_remind(session, order, now=now)

        monkeypatch.setattr(
            OrderService,
            "_remind_guarded",
            staticmethod(remind_after_verdict),
        )

        stats = await OrderService.run_retry_pass(session_factory, now=now)

        assert stats.reminders_sent == 0
        assert stats.reminders_skipped == 1
        assert stats.errors == 0
        async with session_factory() as session:
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
            assert reminders == []
            fresh = await _order_row(session)
            assert fresh.verdict_at is not None
            assert fresh.reminder_sent_at is None
