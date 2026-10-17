"""
Worker tests of module 04_orders (Spec 2.3, 2.4, 3.4, 5.7).

``run_retry_pass`` gets its own sessions from ``session_factory`` —
tests seed and assert through ``session_factory()`` sessions that
commit, never holding ``test_db_session`` open at the same time (the
shared ``:memory:`` pool serialises everything on one connection).
Every pass call hands a fixed ``now``; the bot path runs under the
real ``startup_bot()`` wiring (``orders_bot_started``: READY env,
VK_APP_ID=777). Nothing is mocked at the DB boundary — only the
selector injection point and the module's own pause table are patched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import modules._04_orders.distribution as distribution_module
import modules._04_orders.worker as worker_module
from core.admin.registry import AdminRegistry
from modules._00_core.config_schema import CoreConfig
from modules._00_core.tick_schedule import format_game_time
from modules._02_bot.models import BotOutbox
from modules._04_orders.admin_hooks import (
    MODULE_SLUG,
    register_orders_admin_hooks,
)
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService, RetryPassStats
from modules._04_orders.worker import (
    OrdersWorker,
    WorkerMode,
    get_last_pass_at,
    get_worker_mode,
)
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_order,
)
from tests.modules._04_orders.conftest import seed_author, seed_judge

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


async def _order(session, order_id: str) -> Order:
    return (
        await session.execute(select(Order).where(Order.id == order_id))
    ).scalar_one()


async def _reminder_rows(session) -> list[BotOutbox]:
    return (
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


class TestRetryDistribution:
    """Spec 2.3 step 1 — judge-less orders retried in submission order."""

    async def test_waiting_order_gets_judge_once_candidate_exists(
        self, session_factory, orders_bot_started
    ):
        """An order with no candidates waits; as soon as a player
        becomes reachable the next pass assigns it (Spec 2.3)."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 779001)
            ghost = PlayerFactory.build(vk_user_id=779002, nations=[])
            session.add(ghost)
            order = await make_order(session, author, nation=nation)
            await session.commit()
            order_id, ghost_id = order.id, ghost.id

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats == RetryPassStats(
            assigned=0,
            still_waiting=1,
            reminders_sent=0,
            reminders_skipped=0,
            errors=0,
        )

        # The player gains a nation — reachable now (Spec 3.2).
        async with session_factory() as session:
            session.add(
                NationFactory.build(
                    owner=ghost,
                    name="Поздняя Держава",
                    color_hex="#778899",
                    provinces=[],
                    scheduled_actions=[],
                )
            )
            await session.commit()

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.assigned == 1
        assert stats.still_waiting == 0
        assert stats.errors == 0
        async with session_factory() as session:
            assert (
                await _order(session, order_id)
            ).judge_player_id == ghost_id

    async def test_waiting_orders_served_in_submission_order(
        self, session_factory, orders_started, monkeypatch
    ):
        """Up to ``batch_size`` judge-less orders, oldest
        ``(submitted_at, number)`` first (Spec 2.3)."""
        async with session_factory() as session:
            authors = [
                PlayerFactory.build(
                    vk_user_id=779010 + i, nations=[]
                )
                for i in range(3)
            ]
            session.add_all(authors)
            judge = await seed_judge(session, 779013, nation=True)
            # Insertion order is not submission order: the second row
            # carries the earliest submitted_at.
            orders = [
                await make_order(
                    session,
                    authors[0],
                    submitted_at=NOW - timedelta(hours=2),
                ),
                await make_order(
                    session,
                    authors[1],
                    submitted_at=NOW - timedelta(hours=3),
                ),
                await make_order(
                    session,
                    authors[2],
                    submitted_at=NOW - timedelta(hours=1),
                ),
            ]
            await session.commit()
            judge_id = judge.id
            author_ids = [a.id for a in authors]

        calls: list[str] = []
        real_selector = distribution_module.select_judge_v1

        def recording_selector(author_id, candidates, settings):
            calls.append(author_id)
            return real_selector(author_id, candidates, settings)

        monkeypatch.setattr(
            distribution_module, "judge_selector", recording_selector
        )

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.assigned == 3
        assert stats.errors == 0
        # submitted_at: author1's order is oldest, then author0, then 2.
        assert calls == [author_ids[1], author_ids[0], author_ids[2]]

        async with session_factory() as session:
            for order in orders:
                fresh = await _order(session, order.id)
                assert fresh.judge_player_id == judge_id

    async def test_error_on_one_order_does_not_stop_the_rest(
        self, session_factory, orders_started, monkeypatch
    ):
        """A failing order is logged and counted — the pass continues
        with the next one (Spec 2.3)."""
        async with session_factory() as session:
            author_a = PlayerFactory.build(
                vk_user_id=779101, nations=[]
            )
            author_b = PlayerFactory.build(
                vk_user_id=779102, nations=[]
            )
            session.add_all([author_a, author_b])
            judge = await seed_judge(session, 779103, nation=True)
            first = await make_order(
                session, author_a, submitted_at=NOW - timedelta(hours=2)
            )
            second = await make_order(
                session, author_b, submitted_at=NOW - timedelta(hours=1)
            )
            await session.commit()
            first_id = first.id
            second_id = second.id
            author_a_id = author_a.id
            judge_id = judge.id

        real_selector = distribution_module.select_judge_v1

        def flaky_selector(author_id, candidates, settings):
            if author_id == author_a_id:
                raise RuntimeError("selector boom")
            return real_selector(author_id, candidates, settings)

        monkeypatch.setattr(
            distribution_module, "judge_selector", flaky_selector
        )

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.errors == 1
        assert stats.assigned == 1
        assert stats.still_waiting == 0

        async with session_factory() as session:
            assert (
                await _order(session, first_id)
            ).judge_player_id is None
            assert (
                await _order(session, second_id)
            ).judge_player_id == judge_id


class TestReminders:
    """Spec 2.3 step 2 — one reminder per order, never after the deadline."""

    async def test_reminder_queued_once(
        self, session_factory, orders_bot_started
    ):
        """A due reminder enqueues ORDER_JUDGE_REMINDER and marks
        ``reminder_sent_at``; a second pass queues nothing more."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 779201)
            judge = await seed_judge(
                session, 779202, nation=True, consent="ALLOWED"
            )
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=60),
            )
            await session.commit()
            order_id, judge_id = order.id, judge.id

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.reminders_sent == 1
        assert stats.reminders_skipped == 0
        assert stats.errors == 0

        async with session_factory() as session:
            fresh = await _order(session, order_id)
            assert _aware(fresh.reminder_sent_at) == NOW
            rows = await _reminder_rows(session)
        assert len(rows) == 1
        row = rows[0]
        assert row.player_id == judge_id
        assert row.event_key == f"order_reminder:{order_id}"
        # +72 h deadline from a -60 h submission: 12 h left at NOW.
        assert row.payload == {
            "order_number": 1,
            "hours_left": 12,
            "order_link": "https://vk.com/app777#registry/order-1",
        }

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.reminders_sent == 0
        assert stats.reminders_skipped == 0
        async with session_factory() as session:
            assert len(await _reminder_rows(session)) == 1

    async def test_late_reminder_marked_but_not_queued(
        self, session_factory, orders_bot_started
    ):
        """``now >= deadline_at``: no message, ``reminder_sent_at`` is
        still marked, one INFO line (Spec 2.3 — the task was late)."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 779301)
            judge = await seed_judge(
                session, 779302, nation=True, consent="ALLOWED"
            )
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=80),
            )
            await session.commit()
            order_id = order.id

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.reminders_sent == 0
        assert stats.reminders_skipped == 1
        assert stats.errors == 0

        async with session_factory() as session:
            fresh = await _order(session, order_id)
            assert _aware(fresh.reminder_sent_at) == NOW
            assert await _reminder_rows(session) == []

    async def test_verdict_order_gets_no_reminder(
        self, session_factory, orders_bot_started
    ):
        """A verdict already written takes the row out of the sweep —
        the reminder stays unmarked and nothing is queued."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 779401)
            judge = await seed_judge(
                session, 779402, nation=True, consent="ALLOWED"
            )
            order = await make_order(
                session,
                author,
                nation=nation,
                judge=judge,
                submitted_at=NOW - timedelta(hours=60),
                verdict_at=NOW - timedelta(hours=30),
            )
            await session.commit()
            order_id = order.id

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats == RetryPassStats()

        async with session_factory() as session:
            fresh = await _order(session, order_id)
            assert fresh.reminder_sent_at is None
            assert await _reminder_rows(session) == []

    async def test_hours_left_is_ceiled_hours_with_floor_one(
        self, session_factory, orders_bot_started
    ):
        """Spec 3.4: ``h = max(1, ceil((deadline - now) / 3600 s))`` —
        1.5 h left reads «2», half an hour reads «1»."""
        async with session_factory() as session:
            author, nation = await seed_author(session, 779501)
            judge = await seed_judge(
                session, 779502, nation=True, consent="ALLOWED"
            )
            for minutes in (90, 30):
                await make_order(
                    session,
                    author,
                    nation=nation,
                    judge=judge,
                    submitted_at=NOW - timedelta(hours=2),
                    distributed_at=NOW - timedelta(hours=2),
                    reminder_at=NOW - timedelta(hours=1),
                    deadline_at=NOW + timedelta(minutes=minutes),
                )
            await session.commit()

        stats = await OrderService.run_retry_pass(
            session_factory, now=NOW
        )
        assert stats.reminders_sent == 2
        async with session_factory() as session:
            rows = await _reminder_rows(session)
        assert sorted(r.payload["hours_left"] for r in rows) == [1, 2]


class TestWorkerLoop:
    """The supervised loop (Spec 2.3): survives errors, stops cleanly."""

    async def test_loop_survives_failure_and_stop_ends_it(
        self, session_factory, orders_started, monkeypatch
    ):
        calls = 0
        real_pass = OrderService.run_retry_pass

        async def flaky_pass(factory):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("pass boom")
            return await real_pass(factory)

        monkeypatch.setattr(
            OrderService, "run_retry_pass", staticmethod(flaky_pass)
        )
        monkeypatch.setattr(
            worker_module, "FAILURE_PAUSES_SECONDS", (0.01, 0.01, 0.01)
        )

        worker = OrdersWorker(
            orders_started.distribution, session_factory
        )
        await worker.start()
        try:
            assert get_worker_mode() is WorkerMode.RUNNING

            # Wait for a FINISHED pass, not a started one: calls >= 2
            # only proves the retry began — stopping mid-pass raced the
            # fixture's engine disposal ("closed database").
            for _ in range(500):
                if get_last_pass_at() is not None:
                    break
                await asyncio.sleep(0.01)
            assert calls >= 2
            assert get_last_pass_at() is not None
        finally:
            await worker.stop()
        assert get_worker_mode() is WorkerMode.STOPPED


class TestAdminView:
    """Spec 5.7 — the state view carries the worker mode."""

    async def test_state_view_reports_worker_mode(
        self, test_db_session, orders_started, monkeypatch
    ):
        register_orders_admin_hooks()
        hook = AdminRegistry.get_state_view_hooks()[MODULE_SLUG]

        view = await hook(test_db_session)
        assert view["worker_mode"] == "STOPPED"
        assert view["last_pass_at"] is None

        monkeypatch.setattr(
            worker_module, "_mode", WorkerMode.RUNNING
        )
        monkeypatch.setattr(worker_module, "_last_pass_at", NOW)
        view = await hook(test_db_session)
        assert view["worker_mode"] == "RUNNING"
        tz = CoreConfig.from_yaml(
            CoreConfig.get_default_config_path()
        ).tick.tick_timezone
        assert view["last_pass_at"] == format_game_time(NOW, tz)
