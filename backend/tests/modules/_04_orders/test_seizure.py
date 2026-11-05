"""
Module 04_orders hard-deadline and seizure tests (0.14.0 unit 7b).

Real in-memory DB, rows seeded through the shared factories
(Anti-Mock Guard); the bot path runs under ``orders_bot_started``
(READY env, VK_APP_ID=777). Worker passes open their own sessions
through ``session_factory``. Covers the firm deadline on
``write_verdict``, the ``term_exempt`` flags, the Part C seizure —
the administrator pick, the fine, the recalled outbox rows and the
three announcements — and the administrator exclusion from
``distribute``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import modules._04_orders.distribution as distribution_module
from modules._00_core.models import AdminGrant, JudgeRatingLog, Player
from modules._02_bot.models import BotOutbox
from modules._04_orders.exceptions import (
    OrderDeadlinePassedError,
    OrderRefuseNotAllowedError,
)
from modules._04_orders.models import Order
from modules._04_orders.service import DistributeResult, OrderService
from tests.fixtures.factories import (
    make_consent,
    make_order,
    make_outbox_row,
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge
from tests.modules._04_orders.test_verdict import VALID_VERDICT

ORDERS_URL = "/api/v1/orders"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


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


async def _outbox(session) -> list[BotOutbox]:
    return list((await session.execute(select(BotOutbox))).scalars().all())


async def make_admin(
    session, vk_user_id: int, *, nation: bool = True, consent: str | None = None
) -> Player:
    """A player holding an admin_grants row — the seizure's only
    eligible audience besides the env allowlist."""
    player = await seed_judge(session, vk_user_id, nation=nation, consent=consent)
    session.add(AdminGrant(player_id=player.id, granted_by_vk_user_id=1))
    await session.flush()
    return player


class TestDeadlineIsFirm:
    """``write_verdict`` refuses once the clock passed ``deadline_at``
    — whether or not the worker already ran (7b)."""

    async def test_verdict_refused_after_and_accepted_before_deadline(
        self, client, test_db_session, orders_started
    ):
        """``deadline_at + 1 s``: HTTP 409 ``ORDER_DEADLINE_PASSED``
        and nothing written; one second before: accepted."""
        author, nation = await seed_author(test_db_session, 781001)
        judge = await seed_judge(test_db_session, 781002, nation=True)
        now = datetime.now(UTC)
        late = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=now - timedelta(hours=72),
            reminder_at=now - timedelta(hours=19),
            deadline_at=now - timedelta(seconds=1),
        )
        in_term = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=now - timedelta(hours=71),
            reminder_at=now - timedelta(hours=17),
            deadline_at=now + timedelta(seconds=1),
        )

        response = await client.post(
            f"{ORDERS_URL}/{late.number}/verdict",
            headers=bearer_headers(judge.id),
            json=VALID_VERDICT,
        )
        assert response.status_code == 409
        assert response.json()["code"] == "ORDER_DEADLINE_PASSED"
        await test_db_session.refresh(late)
        assert late.verdict_at is None
        assert late.judge_player_id == judge.id

        response = await client.post(
            f"{ORDERS_URL}/{in_term.number}/verdict",
            headers=bearer_headers(judge.id),
            json=VALID_VERDICT,
        )
        assert response.status_code == 201
        await test_db_session.refresh(in_term)
        assert in_term.verdict_at is not None


class TestSeizure:
    """Part C of ``run_retry_pass`` — the worker's overdue sweep."""

    async def test_seizes_only_the_overdue_nonexempt(
        self, session_factory, orders_bot_started
    ):
        """The pass seizes exactly the judged, undecided, enforced,
        past-deadline order and leaves every other row alone — the
        exempt overdue one included (its reminder claim is never
        touched either)."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781011)
            judge = await seed_judge(session, 781012, nation=True)
            admin = await make_admin(session, 781013)
            seized = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            # An exempt row overdue on paper — the grandfathered
            # shape: reminder due and never claimed.
            exempt = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
                term_exempt=True,
            )
            decided = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
                verdict_at=NOW - timedelta(hours=10),
            )
            fresh = await make_order(session, author, nation=nation, judge=judge)
            await session.commit()
            ids = {
                "seized": seized.id,
                "exempt": exempt.id,
                "decided": decided.id,
                "fresh": fresh.id,
            }
            judge_id, admin_id = judge.id, admin.id

        stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.seized == 1
        assert stats.errors == 0

        async with session_factory() as session:
            row = await session.get(Order, ids["seized"])
            assert row.judge_player_id == admin_id
            assert row.term_exempt is True
            assert row.assignment_no == 2
            assert _aware(row.distributed_at) == NOW
            assert _aware(row.deadline_at) == NOW + timedelta(hours=72)
            assert _aware(row.reminder_at) == NOW + timedelta(hours=54)
            assert _aware(row.reminder_sent_at) == NOW

            kept = await session.get(Order, ids["exempt"])
            assert kept.judge_player_id == judge_id
            assert kept.term_exempt is True
            assert kept.reminder_sent_at is None
            assert (await session.get(Order, ids["decided"])).verdict_at is not None
            fresh_row = await session.get(Order, ids["fresh"])
            assert _aware(fresh_row.deadline_at) > NOW
            assert fresh_row.term_exempt is False

            entries = await _journal(session, judge_id)
            assert len(entries) == 1
            assert entries[0].reason_code == "ORDER_OVERDUE"
            assert entries[0].delta == -5
            assert entries[0].source_key == f"order_overdue:{ids['seized']}:1"

    async def test_never_the_author_or_the_sitting_judge(
        self, session_factory, orders_started, monkeypatch
    ):
        """The pick is uniformly random over the administrators minus
        the author and the sitting judge — the author holding admin
        rights is never eligible."""
        seen: list[list[str]] = []

        class StubRandom:
            def choice(self, seq):
                seen.append(list(seq))
                return seq[0]

        monkeypatch.setattr(distribution_module, "admin_random", StubRandom())

        async with session_factory() as session:
            author, nation = await seed_author(session, 781021)
            # The author is an administrator too — still never eligible.
            session.add(AdminGrant(player_id=author.id, granted_by_vk_user_id=1))
            judge = await seed_judge(session, 781022, nation=True)
            admin = await make_admin(session, 781023)
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            order_id, author_id, judge_id, admin_id = (
                order.id,
                author.id,
                judge.id,
                admin.id,
            )

        stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.seized == 1
        assert seen == [[admin_id]]
        async with session_factory() as session:
            row = await session.get(Order, order_id)
            assert row.judge_player_id == admin_id
            assert row.judge_player_id not in (author_id, judge_id)

    async def test_no_admin_means_no_fine(
        self, session_factory, orders_started, caplog
    ):
        """With the author as the only administrator the order waits
        for the next pass — one warning, no fine, no seizure."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781031)
            session.add(AdminGrant(player_id=author.id, granted_by_vk_user_id=1))
            judge = await seed_judge(session, 781032, nation=True)
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            order_id, judge_id = order.id, judge.id

        with caplog.at_level("WARNING", logger="modules._04_orders.service"):
            stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.seized == 0
        assert stats.errors == 0
        assert "no administrator available" in caplog.text

        async with session_factory() as session:
            row = await session.get(Order, order_id)
            assert row.judge_player_id == judge_id
            assert row.term_exempt is False
            assert await _journal(session, judge_id) == []
            assert (await session.get(Player, judge_id)).judge_rating == 0

    async def test_fine_once_across_two_passes(
        self, session_factory, orders_started
    ):
        """The pass runs twice: the conditional UPDATE claims the row
        once and the idempotent source key backs it — exactly one
        ORDER_OVERDUE entry, rating down by five once."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781041)
            judge = await seed_judge(session, 781042, nation=True)
            await make_admin(session, 781043)
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            order_id, judge_id = order.id, judge.id

        first = await OrderService.run_retry_pass(session_factory, now=NOW)
        second = await OrderService.run_retry_pass(
            session_factory, now=NOW + timedelta(minutes=1)
        )
        assert first.seized == 1
        assert second.seized == 0

        async with session_factory() as session:
            entries = await _journal(session, judge_id)
            assert len(entries) == 1
            assert entries[0].reason_code == "ORDER_OVERDUE"
            assert entries[0].delta == -5
            assert (await session.get(Player, judge_id)).judge_rating == -5

    async def test_three_notices_and_recalled_rows(
        self, session_factory, orders_bot_started
    ):
        """The author gets ORDER_OVERDUE_AUTHOR, the late judge
        ORDER_OVERDUE_JUDGE with the penalty and the administrator
        ORDER_ADMIN_ASSIGNED — distinct keys carrying the new
        assignment number, no names in any payload; the old judge's
        unsent rows are recalled."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781051)
            await make_consent(session, author, state="ALLOWED")
            judge = await seed_judge(session, 781052, nation=True, consent="ALLOWED")
            admin = await make_admin(session, 781053, consent="ALLOWED")
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await make_outbox_row(
                session,
                judge,
                type_key="ORDER_JUDGE_ASSIGNED",
                event_key=f"order_assigned:{order.id}",
            )
            await session.commit()
            order_id = order.id
            author_id, judge_id, admin_id = author.id, judge.id, admin.id

        stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.seized == 1

        async with session_factory() as session:
            rows = await _outbox(session)

        def rows_of(player_id: str, type_key: str) -> list[BotOutbox]:
            return [
                row
                for row in rows
                if row.player_id == player_id and row.type_key == type_key
            ]

        author_rows = rows_of(author_id, "ORDER_OVERDUE_AUTHOR")
        assert len(author_rows) == 1
        assert author_rows[0].event_key == f"order_overdue_author:{order_id}:2"
        assert author_rows[0].payload == {
            "order_number": 1,
            "order_link": "https://vk.com/app777#registry/order-1",
        }

        judge_notice = rows_of(judge_id, "ORDER_OVERDUE_JUDGE")
        assert len(judge_notice) == 1
        assert judge_notice[0].event_key == f"order_overdue_judge:{order_id}:2"
        assert judge_notice[0].payload == {"order_number": 1, "penalty": 5}
        # The old judge's unsent assignment row is recalled.
        old_rows = rows_of(judge_id, "ORDER_JUDGE_ASSIGNED")
        assert len(old_rows) == 1
        assert old_rows[0].status == "DROPPED"
        assert old_rows[0].drop_reason == "CANCELLED"

        admin_rows = rows_of(admin_id, "ORDER_ADMIN_ASSIGNED")
        assert len(admin_rows) == 1
        assert admin_rows[0].event_key == f"order_admin_assigned:{order_id}:2"
        assert admin_rows[0].payload == {
            "order_number": 1,
            "order_link": "https://vk.com/app777#registry/order-1",
        }

        # No name ever rides a payload: only the number, the link and
        # the penalty amount are allowed variable keys.
        for row in rows:
            assert set(row.payload) <= {"order_number", "order_link", "penalty"}

    async def test_seized_order_never_redistributed(
        self, session_factory, orders_started
    ):
        """A seized order keeps a judge, so Part A never offers it to
        the automatic selector again — and a direct ``distribute``
        reports ALREADY_ASSIGNED."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781061)
            judge = await seed_judge(session, 781062, nation=True)
            admin = await make_admin(session, 781063)
            await seed_judge(session, 781064, nation=True)
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            order_id, admin_id = order.id, admin.id

        await OrderService.run_retry_pass(session_factory, now=NOW)
        later = NOW + timedelta(hours=1)
        stats = await OrderService.run_retry_pass(session_factory, now=later)
        assert stats.seized == 0
        assert stats.assigned == 0

        async with session_factory() as session:
            row = await session.get(Order, order_id)
            assert row.judge_player_id == admin_id
            assert row.term_exempt is True
            assert (
                await OrderService.distribute(session, order_id, now=later)
                is DistributeResult.ALREADY_ASSIGNED
            )

    async def test_seizure_error_does_not_stop_the_pass(
        self, session_factory, orders_started, monkeypatch
    ):
        """A failing seizure is logged and counted — the pass
        continues with the next order (Spec 2.3 shape)."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 781071)
            judge = await seed_judge(session, 781072, nation=True)
            await make_admin(session, 781073)
            first = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=90),
            )
            second = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            first_id, second_id = first.id, second.id

        real_guarded = OrderService._seize_guarded

        async def flaky_guarded(session, order_id, *, now):
            if order_id == first_id:
                raise RuntimeError("seizure boom")
            return await real_guarded(session, order_id, now=now)

        monkeypatch.setattr(
            OrderService, "_seize_guarded", staticmethod(flaky_guarded)
        )

        stats = await OrderService.run_retry_pass(session_factory, now=NOW)
        assert stats.errors == 1
        assert stats.seized == 1
        async with session_factory() as session:
            assert (await session.get(Order, second_id)).term_exempt is True


class TestAdminExclusion:
    """Administrators are never candidates of the automatic
    distribution (7b)."""

    async def test_distribute_never_offers_an_admin(
        self, test_db_session, orders_started
    ):
        """With only an administrator besides the author the order
        finds no candidate; a regular player is still picked."""
        author, nation = await seed_author(test_db_session, 781081)
        await make_admin(test_db_session, 781082)
        order = await make_order(test_db_session, author, nation=nation)

        assert (
            await OrderService.distribute(test_db_session, order.id)
            is DistributeResult.NO_CANDIDATES
        )
        await test_db_session.refresh(order)
        assert order.judge_player_id is None

        judge = await seed_judge(test_db_session, 781083, nation=True)
        assert (
            await OrderService.distribute(test_db_session, order.id)
            is DistributeResult.ASSIGNED
        )
        await test_db_session.refresh(order)
        assert order.judge_player_id == judge.id


class TestTermExempt:
    """``term_exempt`` — no overdue mark, no refusal, verdict any
    time (7b)."""

    async def test_admin_assigned_order_is_exempt(
        self, test_db_session, orders_started
    ):
        """``admin_assign_judge`` marks the order exempt: no overdue
        flag, refusal raises ORDER_REFUSE_NOT_ALLOWED and the verdict
        is still writable — even past the nominal deadline."""
        author, nation = await seed_author(test_db_session, 781091)
        judge = await seed_judge(test_db_session, 781092, nation=True)
        order = await make_order(test_db_session, author, nation=nation)
        await OrderService.admin_assign_judge(
            test_db_session, order.number, judge.id
        )
        await test_db_session.refresh(order)
        assert order.term_exempt is True

        # A second order gets the exempt flag directly with a nominal
        # deadline already in the past — the grandfathered shape.
        stale = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=80),
            term_exempt=True,
        )

        view = await OrderService.get_detail(
            test_db_session, number=stale.number, viewer_player_id=judge.id
        )
        assert view.overdue is False
        assert view.refuse_penalty is None

        with pytest.raises(OrderRefuseNotAllowedError) as exc_info:
            await OrderService.refuse(
                test_db_session, player_id=judge.id, number=stale.number
            )
        assert exc_info.value.code == "ORDER_REFUSE_NOT_ALLOWED"

        # The exempt order's nominal deadline lies in the past —
        # the verdict is still accepted.
        view = await OrderService.write_verdict(
            test_db_session,
            player_id=judge.id,
            number=stale.number,
            **VALID_VERDICT,
        )
        assert view.verdict_title == VALID_VERDICT["title"]

    async def test_refuse_not_allowed_maps_to_409(
        self, client, test_db_session, orders_started
    ):
        author, nation = await seed_author(test_db_session, 781101)
        judge = await seed_judge(test_db_session, 781102, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            term_exempt=True,
        )
        response = await client.post(
            f"{ORDERS_URL}/{order.number}/refuse",
            headers=bearer_headers(judge.id),
        )
        assert response.status_code == 409
        assert response.json()["code"] == "ORDER_REFUSE_NOT_ALLOWED"

    async def test_nonexempt_still_reports_overdue(
        self, test_db_session, orders_started
    ):
        """Sanity for the boundary: a non-exempt order past
        ``deadline_at`` still reports ``overdue`` — the flag only
        sleeps for exempt rows."""
        author, nation = await seed_author(test_db_session, 781111)
        judge = await seed_judge(test_db_session, 781112, nation=True)
        order = await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            distributed_at=datetime.now(UTC) - timedelta(hours=80),
        )
        view = await OrderService.get_detail(
            test_db_session, number=order.number, viewer_player_id=judge.id
        )
        assert view.overdue is True

        with pytest.raises(OrderDeadlinePassedError):
            await OrderService.write_verdict(
                test_db_session,
                player_id=judge.id,
                number=order.number,
                **VALID_VERDICT,
            )
