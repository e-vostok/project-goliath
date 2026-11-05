"""
Module 04_orders judge-refusal tests (0.14.0 unit 7a).

Real in-memory DB, rows seeded through the shared factories
(Anti-Mock Guard); the bot path runs under ``orders_bot_started``
(READY env, VK_APP_ID=777). Covers the penalty and its journal
reasons, the release-and-redistribute flow with the assignment
number in the bot event keys, the recalled outbox rows and the
``refuse_penalty`` detail field.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from modules._00_core.models import JudgeRatingLog, Player
from modules._02_bot.models import BotOutbox
from modules._04_orders.exceptions import (
    OrderAlreadyDecidedError,
    OrderDeadlinePassedError,
    OrderNotFoundError,
    OrderVerdictForbiddenError,
)
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import (
    make_consent,
    make_order,
    make_outbox_row,
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

ORDERS_URL = "/api/v1/orders"
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _journal(session, player_id: str) -> list[JudgeRatingLog]:
    return list(
        (
            await session.execute(
                select(JudgeRatingLog).where(JudgeRatingLog.player_id == player_id)
            )
        )
        .scalars()
        .all()
    )


class TestRefuse:
    """``OrderService.refuse`` — the 7a check order and release flow."""

    async def test_refuse_releases_and_redistributes_full_term(
        self, test_db_session, orders_bot_started
    ):
        """Early refusal: −2 with ORDER_REFUSED, the judge appended to
        ``refused_judge_ids``, ``assignment_no`` bumped, the next judge
        seated at once with a full 72 h term — and a repeated refuse
        by the same player is the verdict-path refusal that moves the
        rating no further."""
        author, nation = await seed_author(test_db_session, 780001)
        await make_consent(test_db_session, author, state="ALLOWED")
        judge = await seed_judge(test_db_session, 780002, nation=True)
        second = await seed_judge(test_db_session, 780003, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=NOW - timedelta(hours=10),
        )

        outcome = await OrderService.refuse(
            test_db_session, player_id=judge.id, number=order.number, now=NOW
        )
        assert outcome.penalty == 2
        assert outcome.rating_after == -2

        entries = await _journal(test_db_session, judge.id)
        assert len(entries) == 1
        assert entries[0].reason_code == "ORDER_REFUSED"
        assert entries[0].delta == -2
        assert entries[0].source_key == f"order_refused:{order.id}:1"

        await test_db_session.refresh(order)
        # The refused judge is never picked again while another
        # candidate exists — the order went straight to the next one.
        assert order.judge_player_id == second.id
        assert order.refused_judge_ids == [judge.id]
        assert order.assignment_no == 2
        assert _aware(order.distributed_at) == NOW
        assert _aware(order.deadline_at) == NOW + timedelta(hours=72)

        # A repeated refuse is forbidden and moves nothing.
        with pytest.raises(OrderVerdictForbiddenError):
            await OrderService.refuse(
                test_db_session, player_id=judge.id, number=order.number, now=NOW
            )
        await test_db_session.refresh(judge)
        assert judge.judge_rating == -2
        assert len(await _journal(test_db_session, judge.id)) == 1

    async def test_late_window_penalty(self, test_db_session, orders_started):
        """Inside the last ``late_window_hours`` the refusal costs
        ``penalty_late`` with reason ORDER_REFUSED_LATE."""
        author, nation = await seed_author(test_db_session, 780011)
        judge = await seed_judge(test_db_session, 780012, nation=True)
        await seed_judge(test_db_session, 780013, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=NOW - timedelta(hours=60),
        )  # deadline = NOW + 12 h — inside the 24 h window

        outcome = await OrderService.refuse(
            test_db_session, player_id=judge.id, number=order.number, now=NOW
        )
        assert outcome.penalty == 3
        assert outcome.rating_after == -3
        entries = await _journal(test_db_session, judge.id)
        assert entries[0].reason_code == "ORDER_REFUSED_LATE"

    async def test_after_deadline_refused_without_penalty(
        self, test_db_session, orders_started
    ):
        """``now`` past ``deadline_at``: ORDER_DEADLINE_PASSED, no
        rating change, the assignment untouched (unit 7b's business)."""
        author, nation = await seed_author(test_db_session, 780021)
        judge = await seed_judge(test_db_session, 780022, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=NOW - timedelta(hours=80),
        )

        with pytest.raises(OrderDeadlinePassedError) as exc_info:
            await OrderService.refuse(
                test_db_session, player_id=judge.id, number=order.number, now=NOW
            )
        assert exc_info.value.code == "ORDER_DEADLINE_PASSED"

        await test_db_session.refresh(order)
        assert order.judge_player_id == judge.id
        assert order.refused_judge_ids == []
        assert await _journal(test_db_session, judge.id) == []

    async def test_decided_order_is_already_decided(
        self, test_db_session, orders_started
    ):
        author, nation = await seed_author(test_db_session, 780031)
        judge = await seed_judge(test_db_session, 780032, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            submitted_at=NOW - timedelta(hours=2),
            verdict_at=NOW - timedelta(hours=1),
        )
        with pytest.raises(OrderAlreadyDecidedError):
            await OrderService.refuse(
                test_db_session, player_id=judge.id, number=order.number, now=NOW
            )

    async def test_no_candidate_waits_then_worker_assigns_full_term(
        self, session_factory, orders_started
    ):
        """With no other candidate the freed order waits judge-less;
        the worker's pass seats the next judge later — with a full
        new term counted from the pass moment."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 780041)
            judge = await seed_judge(session, 780042, nation=True)
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                distributed_at=NOW - timedelta(hours=10),
            )
            outcome = await OrderService.refuse(
                session, player_id=judge.id, number=order.number, now=NOW
            )
            await session.commit()
            order_id = order.id
            judge_id = judge.id
        assert outcome.penalty == 2

        later = NOW + timedelta(hours=5)
        async with session_factory() as session:
            second = await seed_judge(session, 780043, nation=True)
            await session.commit()
            second_id = second.id
        stats = await OrderService.run_retry_pass(session_factory, now=later)
        assert stats.assigned == 1
        assert stats.errors == 0

        async with session_factory() as session:
            fresh = await session.get(Order, order_id)
            assert fresh.judge_player_id == second_id
            assert fresh.refused_judge_ids == [judge_id]
            assert fresh.assignment_no == 2
            assert _aware(fresh.distributed_at) == later
            assert _aware(fresh.deadline_at) == later + timedelta(hours=72)

    async def test_notice_keys_and_recalled_rows(
        self, test_db_session, orders_bot_started
    ):
        """The author gets exactly one ORDER_JUDGE_REFUSED keyed
        ``order_judge_refused:<id>`` and no second
        ``ORDER_DISTRIBUTED``; the new judge's assignment row carries
        ``order_assigned:<id>:2``; the refusing judge's unsent rows
        are recalled."""
        author, nation = await seed_author(test_db_session, 780051)
        await make_consent(test_db_session, author, state="ALLOWED")
        judge = await seed_judge(test_db_session, 780052, nation=True)
        second = await seed_judge(
            test_db_session, 780053, nation=True, consent="ALLOWED"
        )
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        await make_outbox_row(
            test_db_session,
            judge,
            type_key="ORDER_JUDGE_ASSIGNED",
            event_key=f"order_assigned:{order.id}",
        )
        await make_outbox_row(
            test_db_session,
            judge,
            type_key="ORDER_JUDGE_REMINDER",
            event_key=f"order_reminder:{order.id}",
        )
        await make_outbox_row(
            test_db_session,
            author,
            type_key="ORDER_DISTRIBUTED",
            event_key=f"order_distributed:{order.id}",
        )

        await OrderService.refuse(
            test_db_session, player_id=judge.id, number=order.number, now=NOW
        )
        await test_db_session.refresh(order)

        author_rows = (
            (
                await test_db_session.execute(
                    select(BotOutbox).where(BotOutbox.player_id == author.id)
                )
            )
            .scalars()
            .all()
        )
        assert [(row.type_key, row.status) for row in author_rows] == [
            ("ORDER_DISTRIBUTED", "PENDING"),
            ("ORDER_JUDGE_REFUSED", "PENDING"),
        ]
        refused_row = next(
            row for row in author_rows if row.type_key == "ORDER_JUDGE_REFUSED"
        )
        assert refused_row.event_key == f"order_judge_refused:{order.id}"
        assert refused_row.payload == {
            "order_number": order.number,
            "order_link": f"https://vk.com/app777#registry/order-{order.number}",
        }

        new_judge_rows = (
            (
                await test_db_session.execute(
                    select(BotOutbox).where(BotOutbox.player_id == second.id)
                )
            )
            .scalars()
            .all()
        )
        assert [(row.type_key, row.event_key) for row in new_judge_rows] == [
            ("ORDER_JUDGE_ASSIGNED", f"order_assigned:{order.id}:2")
        ]

        old_rows = (
            (
                await test_db_session.execute(
                    select(BotOutbox).where(BotOutbox.player_id == judge.id)
                )
            )
            .scalars()
            .all()
        )
        assert all(
            row.status == "DROPPED" and row.drop_reason == "CANCELLED"
            for row in old_rows
        )

    async def test_new_judge_reminder_carries_assignment_number(
        self, session_factory, orders_bot_started
    ):
        """The re-seated judge's due reminder is enqueued under
        ``order_reminder:<id>:2`` — the first judge's key would have
        deduped it away."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 780061)
            judge = await seed_judge(session, 780062, nation=True, consent="ALLOWED")
            second = await seed_judge(
                session, 780063, nation=True, consent="ALLOWED"
            )
            order = await make_order(
                session, author, nation=nation, judge=judge,
                distributed_at=NOW - timedelta(hours=10),
            )
            await OrderService.refuse(
                session, player_id=judge.id, number=order.number, now=NOW
            )
            await session.commit()
            order_id, second_id = order.id, second.id

        # New deadline NOW+72h, reminder at NOW+54h — a pass 60 h on
        # finds it due.
        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW + timedelta(hours=60)
        )
        assert stats.reminders_sent == 1
        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(BotOutbox).where(
                            BotOutbox.type_key == "ORDER_JUDGE_REMINDER",
                            BotOutbox.status == "PENDING",
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 1
        assert rows[0].player_id == second_id
        assert rows[0].event_key == f"order_reminder:{order_id}:2"

    async def test_refuse_penalty_only_for_the_assigned_judge(
        self, test_db_session, orders_started
    ):
        """``refuse_penalty`` shows the amount that would apply right
        now — for the assigned judge alone, null for everyone else and
        once the deadline passed."""
        author, nation = await seed_author(test_db_session, 780071)
        judge = await seed_judge(test_db_session, 780072, nation=True)
        stranger = await seed_judge(test_db_session, 780073, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=10),
        )
        stale = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=80),
        )

        as_judge = await OrderService.get_detail(
            test_db_session, number=order.number, viewer_player_id=judge.id
        )
        assert as_judge.refuse_penalty == 2
        for viewer in (author.id, stranger.id):
            view = await OrderService.get_detail(
                test_db_session, number=order.number, viewer_player_id=viewer
            )
            assert view.refuse_penalty is None

        # Inside the late window the field shows the raised penalty.
        late = await OrderService.get_detail(
            test_db_session, number=stale.number, viewer_player_id=judge.id
        )
        assert late.refuse_penalty is None  # past deadline — impossible


class TestRefuseHttp:
    """``POST /orders/{number}/refuse`` — statuses and the answer."""

    async def test_happy_path_and_forbidden_variants(
        self, client, test_db_session, orders_started
    ):
        author, nation = await seed_author(test_db_session, 780081)
        judge = await seed_judge(test_db_session, 780082, nation=True)
        second = await seed_judge(test_db_session, 780083, nation=True)
        # No nation, no consent — never a candidate (deterministic
        # redistribution to ``second``); a refusal still gets the
        # verdict-path 403.
        stranger = await seed_judge(test_db_session, 780084)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=10),
        )
        judgeless = await make_order(test_db_session, author, nation=nation)

        for viewer, target in (
            (author, order),
            (stranger, order),
            (stranger, judgeless),
        ):
            response = await client.post(
                f"{ORDERS_URL}/{target.number}/refuse",
                headers=bearer_headers(viewer.id),
            )
            assert response.status_code == 403
            assert response.json()["code"] == "ORDER_VERDICT_FORBIDDEN"

        response = await client.post(
            f"{ORDERS_URL}/999/refuse", headers=bearer_headers(stranger.id)
        )
        assert response.status_code == 404
        assert response.json()["code"] == "ORDER_NOT_FOUND"

        response = await client.post(
            f"{ORDERS_URL}/{order.number}/refuse",
            headers=bearer_headers(judge.id),
        )
        assert response.status_code == 200
        assert response.json() == {"penalty": 2, "rating_after": -2}

        await test_db_session.refresh(order)
        assert order.judge_player_id == second.id

    async def test_deadline_passed_maps_to_409(
        self, client, test_db_session, orders_started
    ):
        author, nation = await seed_author(test_db_session, 780091)
        judge = await seed_judge(test_db_session, 780092, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=80),
        )
        response = await client.post(
            f"{ORDERS_URL}/{order.number}/refuse",
            headers=bearer_headers(judge.id),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "ORDER_DEADLINE_PASSED"
        await test_db_session.refresh(judge)
        assert judge.judge_rating == 0

    async def test_admin_assigned_judge_can_refuse(
        self, client, test_db_session, orders_started
    ):
        """Known 7a edge (7b decides): an order given through
        ``admin_assign_judge`` refuses like any other — penalty, release,
        redistribute."""
        author, nation = await seed_author(test_db_session, 780101)
        judge = await seed_judge(test_db_session, 780102, nation=True)
        second = await seed_judge(test_db_session, 780103, nation=True)
        order = await make_order(test_db_session, author, nation=nation)
        await OrderService.admin_assign_judge(
            test_db_session, order.number, judge.id
        )

        response = await client.post(
            f"{ORDERS_URL}/{order.number}/refuse",
            headers=bearer_headers(judge.id),
        )
        assert response.status_code == 200
        assert response.json() == {"penalty": 2, "rating_after": -2}
        await test_db_session.refresh(order)
        assert order.judge_player_id == second.id
        assert order.assignment_no == 2


class TestRefusalDetailHttp:
    async def test_detail_carries_refuse_penalty(
        self, client, test_db_session, orders_started
    ):
        author, nation = await seed_author(test_db_session, 780111)
        judge = await seed_judge(test_db_session, 780112, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=10),
        )
        as_judge = await client.get(
            f"{ORDERS_URL}/{order.number}", headers=bearer_headers(judge.id)
        )
        assert as_judge.json()["refuse_penalty"] == 2
        as_author = await client.get(
            f"{ORDERS_URL}/{order.number}", headers=bearer_headers(author.id)
        )
        assert as_author.json()["refuse_penalty"] is None
