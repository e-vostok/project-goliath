"""
Module 04_orders distribution tests (Spec 2.5, 3.1–3.4, 5.2, Appendix C/T).

``select_judge_v1`` is covered as a pure function — no database.
``OrderService.distribute``/``submit`` run against the real in-memory
DB; the bot path runs under the real ``startup_bot()`` wiring
(``orders_bot_started``: READY env, VK_APP_ID=777). Nothing is mocked.
"""

from __future__ import annotations

import uuid
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules._04_orders.startup as orders_startup_module
from modules._00_core.config_schema import CoreConfig
from modules._02_bot.composer import ComposedMessage, RowView
from modules._02_bot.models import BotOutbox
from modules._02_bot.render import render_message
from modules._02_bot.service import BotService, EnqueueResult
from modules._04_orders.config_schema import JudgeSettings
from modules._04_orders.distribution import JudgeCandidate, select_judge_v1
from modules._04_orders.dto import (
    AssignedOrderDTO,
    AssignedOrdersDTO,
    OrderDetailDTO,
)
from modules._04_orders.models import Order
from modules._04_orders.service import (
    AssignedOrderView,
    DistributeResult,
    OrderDetailView,
    OrderService,
    RegistryOrderView,
)
from tests.fixtures.factories import (
    NationFactory,
    PlayerFactory,
    make_consent,
    make_order,
    utcnow,
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

VALID_TITLE = "Приказ о ночном марш-броске"
VALID_SUMMARY = "Перегруппировать резервы до рассвета."
VALID_URL = "https://vk.com/@night-march"

SETTINGS = JudgeSettings(
    min_rating=0,
    max_pending_verdicts=5,
    require_reachable=True,
    verdict_deadline_hours=72,
    reminder_percent=75,
)


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _c(
    player_id: str,
    *,
    rating: int = 0,
    has_nation: bool = True,
    consented: bool = False,
    pending: int = 0,
    last_assigned_at: datetime | None = None,
) -> JudgeCandidate:
    return JudgeCandidate(
        player_id=player_id,
        rating=rating,
        has_nation=has_nation,
        consented=consented,
        pending=pending,
        last_assigned_at=last_assigned_at,
    )


class TestSelectJudgeV1:
    """The pure selector (Spec 2.5, 3.2–3.3)."""

    def test_orders_by_load_then_age_then_id(self):
        """min(P) first; ties go to the longest-unserved (τ = −∞ for a
        never-assigned judge), then to the smaller player_id."""
        old = NOW - timedelta(hours=10)
        newer = NOW - timedelta(hours=5)
        candidates = [
            _c("newer", pending=0, last_assigned_at=newer),
            _c("older", pending=0, last_assigned_at=old),
            _c("virgin", pending=0),  # never assigned — τ = −∞
            _c("loaded", pending=2),
        ]
        assert select_judge_v1("author", candidates, SETTINGS) == "virgin"
        # Without the never-assigned player the oldest timestamp wins.
        assert select_judge_v1("author", candidates[:2], SETTINGS) == "older"
        # Equal load and equal timestamp: the smaller id decides.
        twins = [
            _c("z-player", pending=1, last_assigned_at=old),
            _c("a-player", pending=1, last_assigned_at=old),
        ]
        assert select_judge_v1("author", twins, SETTINGS) == "a-player"

    def test_author_is_never_chosen(self):
        """INV-O3: the author cannot judge their own order — even as
        the least loaded, even as the only candidate."""
        candidates = [_c("author"), _c("other", pending=3)]
        assert select_judge_v1("author", candidates, SETTINGS) == "other"
        assert select_judge_v1("author", candidates[:1], SETTINGS) is None

    def test_rating_threshold_is_inclusive(self):
        """``rating >= judge.min_rating``: the boundary value counts."""
        strict = SETTINGS.model_copy(update={"min_rating": 10})
        candidates = [_c("below", rating=9), _c("edge", rating=10)]
        assert select_judge_v1("author", candidates, strict) == "edge"
        assert select_judge_v1("author", candidates[:1], strict) is None

    def test_load_limit_is_strict(self):
        """``pending < max_pending_verdicts``: a judge at the limit is
        out; one below the limit is in."""
        strict = SETTINGS.model_copy(update={"max_pending_verdicts": 3})
        candidates = [_c("full", pending=3), _c("room", pending=2)]
        assert select_judge_v1("author", candidates, strict) == "room"
        assert select_judge_v1("author", candidates[:1], strict) is None

    def test_reachability_cases(self):
        """Q: nation OR bot consent; neither is unreachable;
        require_reachable=False admits even the unreachable."""
        nation_only = _c("nation", has_nation=True, consented=False)
        consent_only = _c("consent", has_nation=False, consented=True)
        ghost = _c("ghost", has_nation=False, consented=False)
        assert select_judge_v1("a", [nation_only], SETTINGS) == "nation"
        assert select_judge_v1("a", [consent_only], SETTINGS) == "consent"
        assert select_judge_v1("a", [ghost], SETTINGS) is None
        open_gate = SETTINGS.model_copy(update={"require_reachable": False})
        assert select_judge_v1("a", [ghost], open_gate) == "ghost"


async def _submit(session: AsyncSession, player_id: str):
    return await OrderService.submit(
        session,
        player_id=player_id,
        client_request_id=str(uuid.uuid4()),
        title=VALID_TITLE,
        summary=VALID_SUMMARY,
        article_url=VALID_URL,
    )


class TestDistributeFlow:
    """The DB path of ``distribute`` and its ``submit`` wiring."""

    async def test_no_candidates_then_later_distribute(
        self, test_db_session, orders_started
    ):
        """An unreachable second player is no candidate; the order
        waits — and a later attempt assigns it once the player gains a
        nation (Spec 3.3, INV-O8)."""
        author, nation = await seed_author(test_db_session, 771001)
        ghost = PlayerFactory.build(vk_user_id=771002, nations=[])
        test_db_session.add(ghost)
        await test_db_session.flush()

        outcome = await _submit(test_db_session, author.id)
        assert outcome.created is True
        assert outcome.view.distributed is False
        order = (await test_db_session.execute(select(Order))).scalar_one()
        assert order.judge_player_id is None

        result = await OrderService.distribute(test_db_session, order.id)
        assert result == DistributeResult.NO_CANDIDATES

        # The player gains a nation — reachable now, so the very next
        # attempt assigns them; a third attempt is a no-op.
        test_db_session.add(
            NationFactory.build(
                owner=ghost,
                name="Поздняя Держава",
                color_hex="#778899",
                provinces=[],
                scheduled_actions=[],
            )
        )
        await test_db_session.flush()

        result = await OrderService.distribute(test_db_session, order.id)
        assert result == DistributeResult.ASSIGNED
        await test_db_session.refresh(order)
        assert order.judge_player_id == ghost.id
        assert (
            await OrderService.distribute(test_db_session, order.id)
            == DistributeResult.ALREADY_ASSIGNED
        )

    async def test_submit_assigns_judge_and_queues_two_messages(
        self, test_db_session, orders_bot_started
    ):
        """Spec 3.3 end to end: the second reachable player becomes the
        judge at once; the outbox holds exactly the assignment pair —
        and the text carries the number and nation name, never the
        player-written title or summary (D9)."""
        author, nation = await seed_author(
            test_db_session, 771101, nation_name="Северная Лига"
        )
        await make_consent(test_db_session, author, state="ALLOWED")
        judge = await seed_judge(
            test_db_session, 771102, nation=True, consent="ALLOWED"
        )

        outcome = await _submit(test_db_session, author.id)
        assert outcome.view.distributed is True
        assert outcome.view.can_write_verdict is False  # author view

        order = (await test_db_session.execute(select(Order))).scalar_one()
        assert order.judge_player_id == judge.id
        assert _aware(order.distributed_at) == _aware(order.submitted_at)
        assert order.deadline_at is not None
        assert order.reminder_at is not None

        # The judge is the only viewer allowed to write a verdict.
        as_judge = await OrderService.get_detail(
            test_db_session, number=1, viewer_player_id=judge.id
        )
        assert as_judge.can_write_verdict is True
        as_author = await OrderService.get_detail(
            test_db_session, number=1, viewer_player_id=author.id
        )
        assert as_author.can_write_verdict is False

        rows = (
            (
                await test_db_session.execute(
                    select(BotOutbox).order_by(BotOutbox.player_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        by_recipient = {row.player_id: row for row in rows}

        judge_row = by_recipient[judge.id]
        assert judge_row.type_key == "ORDER_JUDGE_ASSIGNED"
        assert judge_row.event_key == f"order_assigned:{order.id}"
        assert judge_row.payload == {
            "order_number": 1,
            "nation_name": "Северная Лига",
            "order_link": "https://vk.com/app777#registry/order-1",
        }

        author_row = by_recipient[author.id]
        assert author_row.type_key == "ORDER_DISTRIBUTED"
        assert author_row.event_key == f"order_distributed:{order.id}"
        assert author_row.payload == {
            "order_number": 1,
            "order_link": "https://vk.com/app777#registry/order-1",
        }

        # event_at = distributed_at -> expires_at counts from it.
        assert _aware(judge_row.expires_at) == _aware(order.distributed_at) + timedelta(
            minutes=4320
        )

        # Render the judge message through the real renderer: the text
        # quotes the number and the nation — never title or summary.
        view = RowView(
            id=judge_row.id,
            type_key=judge_row.type_key,
            kind=judge_row.kind,
            priority=judge_row.priority,
            counts_toward_cap=judge_row.counts_toward_cap,
            created_at=judge_row.created_at,
            not_before=judge_row.not_before,
            next_attempt_at=judge_row.next_attempt_at,
            expires_at=judge_row.expires_at,
            payload=judge_row.payload,
        )
        text = render_message(
            ComposedMessage((judge_row.id,), "SINGLE", "ORDER_JUDGE_ASSIGNED", False),
            {judge_row.id: view},
            orders_bot_started,
        )
        assert "№1" in text
        assert "Северная Лига" in text
        assert "app777#registry/order-1" in text
        assert VALID_TITLE not in text
        assert VALID_SUMMARY not in text

    async def test_nationless_consented_judge_receives_message(
        self, test_db_session, orders_bot_started
    ):
        """``requires_nation = false``: a judge without a nation but
        with bot consent is eligible and gets the assignment message;
        an existing requires_nation type still skips them."""
        author, _ = await seed_author(test_db_session, 771201)
        await make_consent(test_db_session, author, state="ALLOWED")
        judge = await seed_judge(
            test_db_session, 771202, nation=False, consent="ALLOWED"
        )

        outcome = await _submit(test_db_session, author.id)
        assert outcome.view.distributed is True

        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.player_id == judge.id)
            )
        ).scalar_one()
        assert row.type_key == "ORDER_JUDGE_ASSIGNED"

        # A requires_nation type keeps refusing the same player.
        skipped = await BotService.enqueue(
            test_db_session,
            type_key="RED_ALERT",
            player_id=judge.id,
            event_key="alert:1",
            variables={"event_text": "учебная тревога"},
        )
        assert skipped == EnqueueResult.SKIPPED_NO_NATION
        count = (
            (
                await test_db_session.execute(
                    select(BotOutbox).where(BotOutbox.player_id == judge.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(count) == 1

    async def test_deadline_and_reminder_fixed_at_assignment(
        self, test_db_session, orders_started, monkeypatch
    ):
        """Spec 3.4: deadline/reminder are stamped by integer arithmetic
        at assignment — a later config change never moves them."""
        author, nation = await seed_author(test_db_session, 771301)
        await seed_judge(test_db_session, 771302, nation=True)
        judge_cfg = orders_started.judge

        order = await make_order(test_db_session, author, nation=nation)
        assert (
            await OrderService.distribute(test_db_session, order.id, now=NOW)
            == DistributeResult.ASSIGNED
        )
        await test_db_session.refresh(order)
        assert _aware(order.distributed_at) == NOW
        assert _aware(order.deadline_at) == NOW + timedelta(
            seconds=judge_cfg.deadline_seconds
        )
        assert _aware(order.reminder_at) == NOW + timedelta(
            seconds=judge_cfg.reminder_seconds
        )
        assert order.deadline_at > order.reminder_at

        # A different config applies only to future assignments.
        changed = orders_started.model_copy(
            update={
                "judge": orders_started.judge.model_copy(
                    update={
                        "verdict_deadline_hours": 100,
                        "reminder_percent": 50,
                    }
                )
            }
        )
        monkeypatch.setattr(orders_startup_module, "_orders_config", changed)
        later = NOW + timedelta(hours=1)
        second = await make_order(test_db_session, author, nation=nation)
        assert (
            await OrderService.distribute(test_db_session, second.id, now=later)
            == DistributeResult.ASSIGNED
        )
        await test_db_session.refresh(second)
        assert _aware(second.deadline_at) == later + timedelta(hours=100)
        assert _aware(second.reminder_at) == later + timedelta(hours=50)
        await test_db_session.refresh(order)
        assert _aware(order.deadline_at) == NOW + timedelta(hours=72)
        assert _aware(order.reminder_at) == NOW + timedelta(hours=54)


class TestJudgeAnonymity:
    """INV-O5: no player-facing shape may carry a judge field."""

    def test_no_judge_field_in_dtos_and_views(self):
        for dto in (
            OrderDetailDTO,
            AssignedOrderDTO,
            AssignedOrdersDTO,
        ):
            assert not [name for name in dto.model_fields if "judge" in name]
        for view in (
            OrderDetailView,
            AssignedOrderView,
            RegistryOrderView,
        ):
            assert not [f.name for f in dataclass_fields(view) if "judge" in f.name]

    async def test_assigned_list_via_http(
        self, client, test_db_session, orders_started
    ):
        """GET /orders/assigned returns the caller's undecided orders
        soonest deadline first, ``deadline_text`` formatted
        DD.MM.YYYY HH:MM in tick_timezone — no judge fields."""
        author, nation = await seed_author(
            test_db_session, 771401, nation_name="Северная Лига"
        )
        judge = await seed_judge(test_db_session, 771402, nation=True)
        other = await seed_judge(test_db_session, 771403, nation=True)

        # Submitted 80 h ago: the factory's +72 h deadline already
        # passed -> the order is overdue (distributed < reminder <
        # deadline stays intact, ck_orders_distribution_order).
        past_submit = utcnow() - timedelta(hours=80)
        await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            submitted_at=past_submit,
        )
        await make_order(
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            submitted_at=utcnow() - timedelta(hours=1),
        )
        await make_order(  # verdict written — no longer in the queue
            test_db_session,
            author,
            nation=nation,
            judge=judge,
            verdict_at=utcnow() + timedelta(seconds=1),
        )
        await make_order(  # judged by somebody else — not the caller's
            test_db_session,
            author,
            nation=nation,
            judge=other,
        )

        response = await client.get(
            "/api/v1/orders/assigned", headers=bearer_headers(judge.id)
        )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        items = response.json()["items"]
        assert [item["number"] for item in items] == [1, 2]

        # DD.MM.YYYY HH:MM in the tick timezone (Spec 5.2).
        tz = CoreConfig.from_yaml(
            CoreConfig.get_default_config_path()
        ).tick.tick_timezone
        expected = (
            (past_submit + timedelta(hours=72))
            .astimezone(ZoneInfo(tz))
            .strftime("%d.%m.%Y %H:%M")
        )
        assert items[0] == {
            "number": 1,
            "nation": {
                "name": "Северная Лига",
                "color": "#336699",
                "short_name": nation.short_name,
                "flag_url": None,
            },
            "title": "Тестовый приказ",
            "summary": "Краткая суть тестового приказа.",
            "article_url": "https://vk.com/@test/order-article",
            "deadline_text": expected,
            "overdue": True,
        }
        assert items[1]["overdue"] is False
