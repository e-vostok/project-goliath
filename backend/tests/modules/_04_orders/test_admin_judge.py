"""
Module 04_orders admin judge assignment tests (0.11.0 unit 10a).

Real in-memory DB, rows seeded through the shared factories
(Anti-Mock Guard) — nothing is mocked. ``orders_started`` runs the
real ``startup_orders()`` so the service reads the shipped config;
tests that exercise the bot outbox run under ``orders_bot_started``
(READY env, VK_APP_ID=777). Worker passes open their own sessions
through ``session_factory``, so those tests never request
``test_db_session``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from core.admin.registry import AdminRegistry
from modules._00_core.models import AdminAuditLog
from modules._02_bot.models import BotOutbox
from modules._03_registry.admin_hooks import registry_player_info
from modules._04_orders.exceptions import (
    OrderAlreadyDecidedError,
    OrderJudgeAlreadyAssignedError,
    OrderJudgeIsAuthorError,
    OrderNotFoundError,
    OrderVerdictForbiddenError,
)
from modules._00_core.models import NationImage
from modules._00_core.service import NationService
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import (
    make_nation_image,
    make_order,
    make_outbox_row,
    make_vk_profile,
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

ADMIN_URL = "/api/v1/admin/orders"
ORDERS_URL = "/api/v1/orders"


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _pending_count(session, player_id: str) -> int:
    """The judge's pending-verdict load — the row-derived counter."""
    return await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(
            Order.judge_player_id == player_id,
            Order.verdict_at.is_(None),
        )
    )


async def _audit_rows(session):
    return (
        await session.execute(
            select(AdminAuditLog).order_by(AdminAuditLog.id)
        )
    ).scalars().all()


class TestAdminAssignJudge:
    """``OrderService.admin_assign_judge`` — the 10a service contract."""

    async def test_reassign_moves_judge_and_restarts_timers(
        self, test_db_session, orders_started
    ):
        """The judge moves, all four assignment columns reset to
        ``now``, and ``reminder_sent_at = now`` switches the worker's
        reminder off deliberately (no bot message may reach the new
        judge)."""
        config = orders_started
        author, nation = await seed_author(test_db_session, 910001)
        old_judge = await seed_judge(test_db_session, 910002, nation=True)
        new_judge = await seed_judge(test_db_session, 910003, nation=True)
        old_moment = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=old_judge,
            distributed_at=old_moment,
        )
        moment = old_moment + timedelta(hours=10)

        outcome = await OrderService.admin_assign_judge(
            test_db_session, order.number, new_judge.id, now=moment
        )

        await test_db_session.refresh(order)
        assert order.judge_player_id == new_judge.id
        assert _aware(order.distributed_at) == moment
        assert _aware(order.deadline_at) == moment + timedelta(
            seconds=config.judge.deadline_seconds
        )
        assert _aware(order.reminder_at) == moment + timedelta(
            seconds=config.judge.reminder_seconds
        )
        assert _aware(order.reminder_sent_at) == moment
        assert outcome.order.number == order.number
        assert outcome.previous_judge_player_id == old_judge.id
        assert outcome.cancelled_outbox_rows == 0

    async def test_direct_assignment_retry_skips_and_no_bot_rows(
        self, session_factory, orders_bot_started
    ):
        """A judge given to a judge-less order sticks: the retry pass
        only ever retries ``judge_player_id IS NULL`` rows, and the
        admin path queued no bot rows — while the pass's own
        distribution of a sibling order did."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 910011)
            judge = await seed_judge(
                session, 910012, nation=True, consent="ALLOWED"
            )
            order = await make_order(session, author, nation=nation)
            waiting = await make_order(session, author, nation=nation)
            await session.commit()
            number, order_id = order.number, order.id
            judge_id, waiting_id = judge.id, waiting.id

        moment = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)
        async with session_factory() as session:
            outcome = await OrderService.admin_assign_judge(
                session, number, judge_id, now=moment
            )
            await session.commit()
        assert outcome.previous_judge_player_id is None

        stats = await OrderService.run_retry_pass(session_factory)
        # The pass distributed the still-waiting sibling — proof it
        # ran — and left the admin-assigned order untouched.
        assert stats.assigned == 1
        assert stats.errors == 0

        async with session_factory() as session:
            fresh = await session.get(Order, order_id)
            assert fresh.judge_player_id == judge_id
            assert _aware(fresh.distributed_at) == moment
            # No bot row was created for the admin's assignment; the
            # only rows are the pass's own notifications for the
            # sibling order (their composition follows 02_bot's config).
            rows = (await session.execute(select(BotOutbox))).scalars().all()
            assert rows
            assert all(
                f":{order_id}" not in row.event_key for row in rows
            )
            assert any(
                f":{waiting_id}" in row.event_key for row in rows
            )

    async def test_reassign_cancels_queued_rows_and_silences_reminder(
        self, session_factory, orders_bot_started
    ):
        """Item 2: the previous judge's still-unsent assignment and
        reminder rows are recalled (DROPPED/CANCELLED) in the same
        transaction; terminal and foreign-order rows stay untouched —
        and the reminder sweep then sends nothing for this order even
        after the new reminder_at passes."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 910021)
            old_judge = await seed_judge(
                session, 910022, nation=True, consent="ALLOWED"
            )
            new_judge = await seed_judge(
                session, 910023, nation=True, consent="ALLOWED"
            )
            other_judge = await seed_judge(
                session, 910024, nation=True, consent="ALLOWED"
            )
            order = await make_order(
                session, author, nation=nation, judge=old_judge
            )
            other_order = await make_order(
                session,
                author,
                nation=nation,
                judge=other_judge,
                reminder_sent_at=datetime.now(UTC),
            )
            assigned_row = await make_outbox_row(
                session,
                old_judge,
                type_key="ORDER_JUDGE_ASSIGNED",
                event_key=f"order_assigned:{order.id}",
            )
            reminder_row = await make_outbox_row(
                session,
                old_judge,
                type_key="ORDER_JUDGE_REMINDER",
                event_key=f"order_reminder:{order.id}",
            )
            sent_row = await make_outbox_row(
                session,
                old_judge,
                type_key="ORDER_JUDGE_ASSIGNED",
                event_key="order_assigned:foreign-order-id",
                status="SENT",
            )
            foreign_row = await make_outbox_row(
                session,
                other_judge,
                type_key="ORDER_JUDGE_ASSIGNED",
                event_key=f"order_assigned:{other_order.id}",
            )
            await session.commit()
            number = order.number
            row_ids = {
                "assigned": assigned_row.id,
                "reminder": reminder_row.id,
                "sent": sent_row.id,
                "foreign": foreign_row.id,
            }
            order_id, new_judge_id = order.id, new_judge.id

        async with session_factory() as session:
            outcome = await OrderService.admin_assign_judge(
                session, number, new_judge_id
            )
            await session.commit()
        assert outcome.cancelled_outbox_rows == 2

        async with session_factory() as session:
            async def status_of(row_id):
                row = await session.get(BotOutbox, row_id)
                return row.status, row.drop_reason

            assert await status_of(row_ids["assigned"]) == ("DROPPED", "CANCELLED")
            assert await status_of(row_ids["reminder"]) == ("DROPPED", "CANCELLED")
            assert await status_of(row_ids["sent"]) == ("SENT", None)
            assert await status_of(row_ids["foreign"]) == ("PENDING", None)

        # Far past the new reminder moment — the sweep still claims
        # nothing for this order: reminder_sent_at was stamped.
        stats = await OrderService.run_retry_pass(
            session_factory, now=datetime.now(UTC) + timedelta(hours=60)
        )
        assert stats.reminders_sent == 0
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.player_id == new_judge_id
                    )
                )
            ).scalars().all()
            assert rows == []
            assert all(
                row.status == "DROPPED"
                for row in (
                    await session.execute(
                        select(BotOutbox).where(
                            BotOutbox.event_key.like(f"%:{order_id}")
                        )
                    )
                ).scalars().all()
            )

    async def test_decided_order_refused_before_author_check(
        self, test_db_session, orders_started
    ):
        """ORDER_ALREADY_DECIDED — and the check order holds even when
        the candidate is also the author."""
        author, nation = await seed_author(test_db_session, 910031)
        judge = await seed_judge(test_db_session, 910032, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            verdict_at=datetime.now(UTC),
            submitted_at=datetime.now(UTC) - timedelta(hours=1),
        )
        with pytest.raises(OrderAlreadyDecidedError) as decided:
            await OrderService.admin_assign_judge(
                test_db_session, order.number, author.id
            )
        assert decided.value.code == "ORDER_ALREADY_DECIDED"

        await test_db_session.refresh(order)
        assert order.judge_player_id == judge.id

    async def test_author_as_judge_refused(self, test_db_session, orders_started):
        author, nation = await seed_author(test_db_session, 910041)
        order = await make_order(test_db_session, author, nation=nation)
        with pytest.raises(OrderJudgeIsAuthorError) as refused:
            await OrderService.admin_assign_judge(
                test_db_session, order.number, author.id
            )
        assert refused.value.code == "JUDGE_IS_AUTHOR"

    async def test_same_judge_refused(self, test_db_session, orders_started):
        author, nation = await seed_author(test_db_session, 910051)
        judge = await seed_judge(test_db_session, 910052, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        with pytest.raises(OrderJudgeAlreadyAssignedError) as refused:
            await OrderService.admin_assign_judge(
                test_db_session, order.number, judge.id
            )
        assert refused.value.code == "ALREADY_JUDGE"

    async def test_unknown_order_refused(self, test_db_session, orders_started):
        judge = await seed_judge(test_db_session, 910061, nation=True)
        with pytest.raises(OrderNotFoundError):
            await OrderService.admin_assign_judge(
                test_db_session, 999, judge.id
            )

    async def test_threshold_limit_and_reachability_do_not_apply(
        self, test_db_session, orders_started
    ):
        """The admin path skips every gate: a judge below
        ``judge.min_rating``, one already at ``max_pending_verdicts``
        and an unreachable one (no nation, no consent — this is also
        how an administrator could name themselves) are all accepted."""
        config = orders_started
        author, nation = await seed_author(test_db_session, 910071)
        weak = await seed_judge(
            test_db_session, 910072, rating=config.judge.min_rating - 10
        )
        busy = await seed_judge(test_db_session, 910073, nation=True)
        ghost = await seed_judge(test_db_session, 910074)
        for _ in range(config.judge.max_pending_verdicts):
            await make_order(
                test_db_session, author, nation=nation, judge=busy
            )
        one = await make_order(test_db_session, author, nation=nation)
        two = await make_order(test_db_session, author, nation=nation)
        three = await make_order(test_db_session, author, nation=nation)

        await OrderService.admin_assign_judge(
            test_db_session, one.number, weak.id
        )
        await OrderService.admin_assign_judge(
            test_db_session, two.number, busy.id
        )
        await OrderService.admin_assign_judge(
            test_db_session, three.number, ghost.id
        )

        for order, judge in ((one, weak), (two, busy), (three, ghost)):
            await test_db_session.refresh(order)
            assert order.judge_player_id == judge.id
        assert (
            await _pending_count(test_db_session, busy.id)
            == config.judge.max_pending_verdicts + 1
        )

    async def test_previous_judge_loses_verdict_new_judge_writes(
        self, test_db_session, orders_started
    ):
        """After the move the old judge hits the existing
        ORDER_VERDICT_FORBIDDEN and only the new judge can write."""
        author, nation = await seed_author(test_db_session, 910081)
        old_judge = await seed_judge(test_db_session, 910082, nation=True)
        new_judge = await seed_judge(test_db_session, 910083, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=old_judge
        )

        await OrderService.admin_assign_judge(
            test_db_session, order.number, new_judge.id
        )

        verdict = {
            "title": "Вердикт по приказу",
            "summary": "Приказ рассмотрен и принят к исполнению.",
            "article_url": "https://vk.com/@verdict-ten-a",
        }
        with pytest.raises(OrderVerdictForbiddenError):
            await OrderService.write_verdict(
                test_db_session,
                player_id=old_judge.id,
                number=order.number,
                **verdict,
            )
        view = await OrderService.write_verdict(
            test_db_session,
            player_id=new_judge.id,
            number=order.number,
            **verdict,
        )
        assert view.verdict_title == verdict["title"]

    async def test_load_counters_follow_the_rows(
        self, test_db_session, orders_started
    ):
        """Judge load is derived from the rows, not a counter: the
        reassigned order leaves the old judge's queue and count and
        joins the new one's — nothing else is recomputed."""
        author, nation = await seed_author(test_db_session, 910091)
        old_judge = await seed_judge(test_db_session, 910092, nation=True)
        new_judge = await seed_judge(test_db_session, 910093, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=old_judge
        )

        assert await _pending_count(test_db_session, old_judge.id) == 1
        assert await _pending_count(test_db_session, new_judge.id) == 0

        await OrderService.admin_assign_judge(
            test_db_session, order.number, new_judge.id
        )

        assert await _pending_count(test_db_session, old_judge.id) == 0
        assert await _pending_count(test_db_session, new_judge.id) == 1
        assert (
            await OrderService.list_assigned(
                test_db_session, player_id=old_judge.id
            )
            == []
        )
        assert [
            view.number
            for view in await OrderService.list_assigned(
                test_db_session, player_id=new_judge.id
            )
        ] == [order.number]


class TestAdminOrdersApi:
    """The three endpoints — list, preview, assign — behind require_admin."""

    async def _admin(self, session, monkeypatch, vk=900001):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", str(vk))
        return await seed_judge(session, vk, nation=True)

    async def test_list_filters_search_and_paging(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910101)
        judge = await seed_judge(test_db_session, 910102, nation=True)
        waiting = await make_order(
            test_db_session, author, nation=nation, title="Ждёт судью"
        )
        assigned = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            title="У судьи на столе",
        )
        decided = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            verdict_at=datetime.now(UTC),
            submitted_at=datetime.now(UTC) - timedelta(hours=1),
            title="Вердикт вынесен",
        )
        headers = bearer_headers(admin.id)

        response = await client.get(ADMIN_URL, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        # Newest number first.
        assert [item["number"] for item in body["items"]] == [
            decided.number,
            assigned.number,
            waiting.number,
        ]
        item = body["items"][1]
        assert item["title"] == "У судьи на столе"
        assert item["author_nation_short_name"] == nation.short_name
        assert item["judge_vk_user_id"] == judge.vk_user_id
        assert item["status"] == "AWAITING_VERDICT"
        assert item["deadline_at"] is not None
        assert item["overdue"] is False
        assert body["items"][0]["status"] == "DECIDED"
        assert body["items"][2]["status"] == "NO_JUDGE"
        assert body["items"][2]["judge_vk_user_id"] is None
        assert body["items"][2]["deadline_at"] is None

        for status, expected in (
            ("waiting", {waiting.number}),
            ("assigned", {assigned.number}),
            ("decided", {decided.number}),
            ("all", {waiting.number, assigned.number, decided.number}),
        ):
            filtered = await client.get(
                ADMIN_URL, params={"status": status}, headers=headers
            )
            assert filtered.status_code == 200
            assert {
                item["number"] for item in filtered.json()["items"]
            } == expected

        # Search matches a number exactly or a title substring.
        by_number = await client.get(
            ADMIN_URL, params={"search": str(waiting.number)}, headers=headers
        )
        assert [i["number"] for i in by_number.json()["items"]] == [
            waiting.number
        ]
        by_title = await client.get(
            ADMIN_URL, params={"search": "столе"}, headers=headers
        )
        assert [i["number"] for i in by_title.json()["items"]] == [
            assigned.number
        ]

        page = await client.get(
            ADMIN_URL,
            params={"limit": 1, "offset": 1},
            headers=headers,
        )
        assert page.status_code == 200
        assert page.json()["total"] == 3
        assert [i["number"] for i in page.json()["items"]] == [
            assigned.number
        ]

    async def test_preview_blockers_and_warnings(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        """Read-only preview: the blocker is the service's first
        refusal and every warning carries a ready Russian text built
        from the config thresholds."""
        config = orders_started
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910111)
        clean = await seed_judge(test_db_session, 910112, nation=True)
        ghost = await seed_judge(test_db_session, 910113)
        weak = await seed_judge(
            test_db_session,
            910114,
            rating=config.judge.min_rating - 5,
            nation=True,
        )
        busy = await seed_judge(test_db_session, 910115, nation=True)
        for _ in range(config.judge.max_pending_verdicts):
            await make_order(
                test_db_session, author, nation=nation, judge=busy
            )
        order = await make_order(test_db_session, author, nation=nation)
        headers = bearer_headers(admin.id)

        async def preview(number, vk):
            response = await client.get(
                f"{ADMIN_URL}/{number}/judge-preview",
                params={"judge_vk_user_id": vk},
                headers=headers,
            )
            assert response.status_code == 200, response.text
            return response.json()

        body = await preview(order.number, clean.vk_user_id)
        assert body["blocker"] is None
        assert body["warnings"] == []
        assert body["current_judge"] is None
        assert body["new_judge"]["vk_user_id"] == clean.vk_user_id

        warnings = (await preview(order.number, ghost.vk_user_id))["warnings"]
        unreachable = [w for w in warnings if w["code"] == "JUDGE_UNREACHABLE"]
        assert unreachable and "не узнает об этом приказе" in unreachable[0]["text"]

        warnings = (await preview(order.number, weak.vk_user_id))["warnings"]
        rating = [w for w in warnings if w["code"] == "JUDGE_RATING_BELOW"]
        assert rating and str(config.judge.min_rating) in rating[0]["text"]

        warnings = (await preview(order.number, busy.vk_user_id))["warnings"]
        limit = [w for w in warnings if w["code"] == "JUDGE_AT_PENDING_LIMIT"]
        assert limit and str(config.judge.max_pending_verdicts) in limit[0]["text"]

        judged = await make_order(
            test_db_session, author, nation=nation, judge=clean
        )
        decided = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=clean,
            verdict_at=datetime.now(UTC),
            submitted_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert (await preview(decided.number, clean.vk_user_id))[
            "blocker"
        ] == "ORDER_ALREADY_DECIDED"
        assert (await preview(order.number, author.vk_user_id))[
            "blocker"
        ] == "JUDGE_IS_AUTHOR"
        same = await preview(judged.number, clean.vk_user_id)
        assert same["blocker"] == "ALREADY_JUDGE"
        assert same["current_judge"]["vk_user_id"] == clean.vk_user_id

        # Nothing the preview did wrote to the orders row.
        await test_db_session.refresh(order)
        assert order.judge_player_id is None

        unknown = await client.get(
            f"{ADMIN_URL}/{order.number}/judge-preview",
            params={"judge_vk_user_id": 42424242},
            headers=headers,
        )
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "PLAYER_NOT_FOUND"

    async def test_assign_assigns_audits_and_returns_item(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        """One POST assigns the judge, writes exactly one audit row
        with the Russian sentence built from the player-info names,
        and answers with the order's list item."""
        if "03_registry" not in AdminRegistry.get_player_info_hooks():
            AdminRegistry.register_player_info(
                "03_registry", registry_player_info, None
            )
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910121)
        old_judge = await seed_judge(test_db_session, 910122, nation=True)
        new_judge = await seed_judge(test_db_session, 910123, nation=True)
        await make_vk_profile(
            test_db_session, old_judge, first_name="Дмитрий", last_name="Соколов"
        )
        await make_vk_profile(
            test_db_session, new_judge, first_name="Ольга", last_name="Ветрова"
        )
        judged = await make_order(
            test_db_session, author, nation=nation, judge=old_judge
        )
        fresh = await make_order(test_db_session, author, nation=nation)
        headers = bearer_headers(admin.id)

        assign = await client.post(
            f"{ADMIN_URL}/{fresh.number}/judge",
            json={"judge_vk_user_id": new_judge.vk_user_id},
            headers=headers,
        )
        assert assign.status_code == 200, assign.text
        item = assign.json()
        assert item["status"] == "AWAITING_VERDICT"
        assert item["judge_vk_user_id"] == new_judge.vk_user_id
        assert item["judge_name"] == "Ольга Ветрова"
        assert item["deadline_at"] is not None

        reassign = await client.post(
            f"{ADMIN_URL}/{judged.number}/judge",
            json={"judge_vk_user_id": new_judge.vk_user_id},
            headers=headers,
        )
        assert reassign.status_code == 200, reassign.text

        rows = await _audit_rows(test_db_session)
        assert [row.action for row in rows] == [
            "order.assign_judge",
            "order.assign_judge",
        ]
        first, second = rows
        assert first.actor_vk_user_id == admin.vk_user_id
        assert first.target_type == "order"
        assert first.target_id == str(fresh.number)
        assert first.summary == (
            f"Приказу № {fresh.number} назначен судья Ольга Ветрова."
        )
        assert set(first.details) == {
            "order_id",
            "previous_judge_player_id",
            "judge_player_id",
        }
        assert first.details["judge_player_id"] == new_judge.id
        assert first.details["previous_judge_player_id"] is None
        assert second.summary == (
            f"Судья приказа № {judged.number} заменён: "
            "Дмитрий Соколов → Ольга Ветрова."
        )
        assert second.details["previous_judge_player_id"] == old_judge.id

        await test_db_session.refresh(fresh)
        await test_db_session.refresh(judged)
        assert fresh.judge_player_id == new_judge.id
        assert judged.judge_player_id == new_judge.id

    async def test_assign_refusals_write_no_audit(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910131)
        judge = await seed_judge(test_db_session, 910132, nation=True)
        decided = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            verdict_at=datetime.now(UTC),
            submitted_at=datetime.now(UTC) - timedelta(hours=1),
        )
        judged = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        fresh = await make_order(test_db_session, author, nation=nation)
        headers = bearer_headers(admin.id)

        cases = [
            (decided.number, judge.vk_user_id, 409, "ORDER_ALREADY_DECIDED"),
            (fresh.number, author.vk_user_id, 409, "JUDGE_IS_AUTHOR"),
            (judged.number, judge.vk_user_id, 409, "ALREADY_JUDGE"),
            (fresh.number, 42424243, 404, "PLAYER_NOT_FOUND"),
            (9999, judge.vk_user_id, 404, "ORDER_NOT_FOUND"),
        ]
        for number, vk, status, code in cases:
            response = await client.post(
                f"{ADMIN_URL}/{number}/judge",
                json={"judge_vk_user_id": vk},
                headers=headers,
            )
            assert response.status_code == status, response.text
            assert response.json()["code"] == code

        assert await _audit_rows(test_db_session) == []

    async def test_non_admin_denied_everywhere(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "424242")
        author, nation = await seed_author(test_db_session, 910141)
        player = await seed_judge(test_db_session, 910142, nation=True)
        order = await make_order(test_db_session, author, nation=nation)
        headers = bearer_headers(player.id)

        for method, url in (
            ("GET", ADMIN_URL),
            ("GET", f"{ADMIN_URL}/{order.number}/judge-preview"),
            ("POST", f"{ADMIN_URL}/{order.number}/judge"),
        ):
            response = await client.request(
                method,
                url,
                params={"judge_vk_user_id": player.vk_user_id},
                json={"judge_vk_user_id": player.vk_user_id},
                headers=headers,
            )
            assert response.status_code == 403, response.text

        unauthenticated = await client.get(ADMIN_URL)
        assert unauthenticated.status_code == 401

    async def test_players_never_learn_the_judge(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        """INV-O5 unchanged: the admin reassignment shows up in the
        player API only as ``distributed`` — no judge field, no hint —
        and the verdict rights move with the row."""
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910151)
        old_judge = await seed_judge(test_db_session, 910152, nation=True)
        new_judge = await seed_judge(test_db_session, 910153, nation=True)
        stranger = await seed_judge(test_db_session, 910154, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=old_judge
        )

        response = await client.post(
            f"{ADMIN_URL}/{order.number}/judge",
            json={"judge_vk_user_id": new_judge.vk_user_id},
            headers=bearer_headers(admin.id),
        )
        assert response.status_code == 200

        detail = await client.get(
            f"{ORDERS_URL}/{order.number}",
            headers=bearer_headers(stranger.id),
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["distributed"] is True
        assert body["can_write_verdict"] is False
        assert "judge" not in body

        old_queue = await client.get(
            f"{ORDERS_URL}/assigned", headers=bearer_headers(old_judge.id)
        )
        new_queue = await client.get(
            f"{ORDERS_URL}/assigned", headers=bearer_headers(new_judge.id)
        )
        assert old_queue.json()["items"] == []
        assert [item["number"] for item in new_queue.json()["items"]] == [
            order.number
        ]

    async def test_list_and_judge_answer_carry_flag_thumb_url(
        self, client, test_db_session, orders_started, monkeypatch
    ):
        """0.12.0 unit 9: the author nation's CURRENT flag by
        order.nation_id — an order submitted before the upload shows
        the flag after it, a deleted nation lands null; one
        ``image_refs`` call per page."""
        admin = await self._admin(test_db_session, monkeypatch)
        author, nation = await seed_author(test_db_session, 910161)
        judge = await seed_judge(test_db_session, 910162, nation=True)
        # The order exists BEFORE the flag upload.
        order = await make_order(
            test_db_session, author, nation=nation, title="С флагом"
        )
        headers = bearer_headers(admin.id)

        calls = []
        original = NationService.image_refs

        async def counting(session, nation_ids):
            calls.append(list(nation_ids))
            return await original(session, nation_ids)

        monkeypatch.setattr(NationService, "image_refs", counting)

        # No flag yet — null.
        response = await client.get(ADMIN_URL, headers=headers)
        assert response.status_code == 200
        assert len(calls) == 1
        item = next(
            i for i in response.json()["items"] if i["number"] == order.number
        )
        assert item["flag_thumb_url"] is None

        # The upload lands afterwards — the same order now carries it.
        await make_nation_image(
            test_db_session, nation, kind="flag", sha256="a" * 64
        )
        calls.clear()
        response = await client.get(ADMIN_URL, headers=headers)
        assert len(calls) == 1
        item = next(
            i for i in response.json()["items"] if i["number"] == order.number
        )
        assert item["flag_thumb_url"] == f"/api/v1/images/{'a' * 64}/thumb"

        # POST /{n}/judge answers the same item shape.
        assigned = await client.post(
            f"{ADMIN_URL}/{order.number}/judge",
            json={"judge_vk_user_id": judge.vk_user_id},
            headers=headers,
        )
        assert assigned.status_code == 200
        assert assigned.json()["flag_thumb_url"] == (
            f"/api/v1/images/{'a' * 64}/thumb"
        )

        # The nation is gone — the snapshot id finds no row, null.
        for row in (
            await test_db_session.execute(
                select(NationImage).where(NationImage.nation_id == nation.id)
            )
        ).scalars():
            await test_db_session.delete(row)
        await test_db_session.delete(nation)
        await test_db_session.flush()

        response = await client.get(ADMIN_URL, headers=headers)
        item = next(
            i for i in response.json()["items"] if i["number"] == order.number
        )
        assert item["flag_thumb_url"] is None
