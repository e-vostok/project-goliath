"""
Module 04_orders verdict tests (Spec 5.1–5.3, INV-O1/O5/O8/O13).

Real in-memory DB, rows seeded through the shared factories
(Anti-Mock Guard) — nothing is mocked. ``orders_started`` runs the
real ``startup_orders()`` so the service reads the shipped config;
the bot path runs under ``orders_bot_started`` (READY env,
VK_APP_ID=777).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from modules._02_bot.composer import ComposedMessage, RowView
from modules._02_bot.models import BotOutbox
from modules._02_bot.render import render_message
from modules._04_orders.models import Order, OrderStage, stage_of
from modules._04_orders.service import OrderService
from tests.fixtures.factories import make_consent, make_order, utcnow
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

ORDERS_URL = "/api/v1/orders"

VALID_VERDICT = {
    "title": "Вердикт по приказу",
    "summary": "Приказ рассмотрен и принят к исполнению.",
    "article_url": "https://vk.com/@verdict-one",
}


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


class TestWriteVerdict:
    """``OrderService.write_verdict`` — the Spec 5.1 check order."""

    async def test_judge_writes_verdict_and_counters_drop(
        self, test_db_session, orders_started
    ):
        """The verdict lands, the stage becomes VERDICT, the judge's
        pending slot and the author's unresolved slot are both freed
        (Spec Part 1, INV-O15)."""
        author, nation = await seed_author(test_db_session, 773001)
        judge = await seed_judge(test_db_session, 773002, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        assert (
            await OrderService.unresolved_count(
                test_db_session, player_id=author.id
            )
            == 1
        )

        view = await OrderService.write_verdict(
            test_db_session,
            player_id=judge.id,
            number=order.number,
            **VALID_VERDICT,
        )

        assert view.verdict_title == VALID_VERDICT["title"]
        assert view.verdict_summary == VALID_VERDICT["summary"]
        assert view.verdict_url == VALID_VERDICT["article_url"]
        assert view.can_write_verdict is False

        await test_db_session.refresh(order)
        assert stage_of(order) == OrderStage.VERDICT
        assert order.verdict_at is not None
        assert _aware(order.verdict_at) >= _aware(order.distributed_at)
        # INV-O13: the effects reserve stays NULL.
        assert order.verdict_effects is None
        # INV-O1: the write touched nothing but the verdict columns.
        assert order.judge_player_id == judge.id

        # The judge's pending workload dropped to zero.
        pending = await test_db_session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.judge_player_id == judge.id,
                Order.verdict_at.is_(None),
            )
        )
        assert pending == 0
        # ...and so did the author's unresolved count.
        assert (
            await OrderService.unresolved_count(
                test_db_session, player_id=author.id
            )
            == 0
        )

        # The judge's queue no longer lists the order.
        assert await OrderService.list_assigned(
            test_db_session, player_id=judge.id
        ) == []

    async def test_forbidden_response_is_byte_identical(
        self, client, test_db_session, orders_started
    ):
        """INV-O5: the author, a stranger and an order without a judge
        all get one and the same ORDER_VERDICT_FORBIDDEN answer."""
        author, nation = await seed_author(test_db_session, 773101)
        judge = await seed_judge(test_db_session, 773102, nation=True)
        stranger = await seed_judge(test_db_session, 773103, nation=True)
        judged = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        judgeless = await make_order(
            test_db_session, author, nation=nation
        )

        as_author = await client.post(
            f"{ORDERS_URL}/{judged.number}/verdict",
            json=VALID_VERDICT,
            headers=bearer_headers(author.id),
        )
        as_stranger = await client.post(
            f"{ORDERS_URL}/{judged.number}/verdict",
            json=VALID_VERDICT,
            headers=bearer_headers(stranger.id),
        )
        no_judge = await client.post(
            f"{ORDERS_URL}/{judgeless.number}/verdict",
            json=VALID_VERDICT,
            headers=bearer_headers(stranger.id),
        )

        assert as_author.status_code == 403
        assert as_stranger.status_code == 403
        assert no_judge.status_code == 403
        # Byte-identical bodies — no hint about the assignment leaks.
        assert (
            as_author.content == as_stranger.content == no_judge.content
        )
        assert as_author.json()["code"] == "ORDER_VERDICT_FORBIDDEN"

        await test_db_session.refresh(judged)
        await test_db_session.refresh(judgeless)
        assert judged.verdict_at is None
        assert judgeless.verdict_at is None

    async def test_second_verdict_refused_first_untouched(
        self, client, test_db_session, orders_started
    ):
        """INV-O1: the verdict is written once — a second attempt gets
        ORDER_VERDICT_EXISTS and the stored text does not move."""
        author, nation = await seed_author(test_db_session, 773201)
        judge = await seed_judge(test_db_session, 773202, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        headers = bearer_headers(judge.id)
        url = f"{ORDERS_URL}/{order.number}/verdict"

        first = await client.post(
            url, json=VALID_VERDICT, headers=headers
        )
        assert first.status_code == 201
        body = first.json()
        assert body["verdict"] == VALID_VERDICT
        assert body["can_write_verdict"] is False
        assert body["overdue"] is False

        again = await client.post(
            url,
            json={**VALID_VERDICT, "title": "Совсем другой вердикт"},
            headers=headers,
        )
        assert again.status_code == 409
        assert again.json()["code"] == "ORDER_VERDICT_EXISTS"

        await test_db_session.refresh(order)
        assert order.verdict_title == VALID_VERDICT["title"]
        assert order.verdict_summary == VALID_VERDICT["summary"]

        # GET returns the same verdict block to any viewer.
        detail = await client.get(
            f"{ORDERS_URL}/{order.number}",
            headers=bearer_headers(author.id),
        )
        assert detail.json()["verdict"] == VALID_VERDICT
        assert detail.json()["can_write_verdict"] is False

    async def test_invalid_fields_write_nothing(
        self, client, test_db_session, orders_started
    ):
        """Title, summary and URL failures answer with their own
        codes — the verdict columns stay empty (Spec 5.3)."""
        author, nation = await seed_author(test_db_session, 773301)
        judge = await seed_judge(test_db_session, 773302, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )
        headers = bearer_headers(judge.id)
        url = f"{ORDERS_URL}/{order.number}/verdict"

        for body, code in (
            (
                {**VALID_VERDICT, "title": "no"},
                "ORDER_TITLE_INVALID",
            ),
            (
                {**VALID_VERDICT, "summary": "коротко"},
                "ORDER_SUMMARY_INVALID",
            ),
            (
                {
                    **VALID_VERDICT,
                    "article_url": "https://evil.example.com/@x",
                },
                "ORDER_URL_INVALID",
            ),
        ):
            response = await client.post(
                url, json=body, headers=headers
            )
            assert response.status_code == 422
            assert response.json()["code"] == code

        await test_db_session.refresh(order)
        assert order.verdict_at is None
        assert order.verdict_title is None
        assert order.verdict_summary is None
        assert order.verdict_url is None

    async def test_effects_field_rejected(
        self, client, test_db_session, orders_started
    ):
        """INV-O13: an ``effects`` field fails DTO validation with
        422 — ``verdict_effects`` stays NULL."""
        author, nation = await seed_author(test_db_session, 773401)
        judge = await seed_judge(test_db_session, 773402, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )

        response = await client.post(
            f"{ORDERS_URL}/{order.number}/verdict",
            json={**VALID_VERDICT, "effects": {"strength": 10}},
            headers=bearer_headers(judge.id),
        )
        assert response.status_code == 422

        await test_db_session.refresh(order)
        assert order.verdict_effects is None
        assert order.verdict_at is None

    async def test_author_gets_verdict_ready_message(
        self, test_db_session, orders_bot_started
    ):
        """ORDER_VERDICT_READY lands in the author's outbox keyed by
        the order and stamped with the verdict moment — the payload
        carries the number and the link, never the verdict's title or
        summary (D9, Appendix C)."""
        author, nation = await seed_author(
            test_db_session, 773501, nation_name="Северная Лига"
        )
        await make_consent(test_db_session, author, state="ALLOWED")
        judge = await seed_judge(test_db_session, 773502, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )

        await OrderService.write_verdict(
            test_db_session,
            player_id=judge.id,
            number=order.number,
            **VALID_VERDICT,
        )
        await test_db_session.refresh(order)

        row = (
            await test_db_session.execute(
                select(BotOutbox).where(BotOutbox.player_id == author.id)
            )
        ).scalar_one()
        assert row.type_key == "ORDER_VERDICT_READY"
        assert row.event_key == f"order_verdict:{order.id}"
        assert row.payload == {
            "order_number": order.number,
            "order_link": (
                f"https://vk.com/app777#registry/order-{order.number}"
            ),
        }
        # event_at = verdict_at -> expires_at counts from it.
        assert _aware(row.expires_at) == _aware(
            order.verdict_at
        ) + timedelta(minutes=4320)

        # The rendered text quotes the number and the link — never the
        # verdict's wording (Spec 0, D9).
        view = RowView(
            id=row.id,
            type_key=row.type_key,
            kind=row.kind,
            priority=row.priority,
            counts_toward_cap=row.counts_toward_cap,
            created_at=row.created_at,
            not_before=row.not_before,
            next_attempt_at=row.next_attempt_at,
            expires_at=row.expires_at,
            payload=row.payload,
        )
        text = render_message(
            ComposedMessage(
                (row.id,), "SINGLE", "ORDER_VERDICT_READY", False
            ),
            {row.id: view},
            orders_bot_started,
        )
        assert f"№{order.number}" in text
        assert "app777#registry/order-" in text
        assert VALID_VERDICT["title"] not in text
        assert VALID_VERDICT["summary"] not in text

    async def test_bot_off_does_not_stop_the_verdict(
        self, test_db_session, orders_started, bot_off_env
    ):
        """INV-O8: with the bot off nothing is enqueued — and the
        verdict still lands."""
        author, nation = await seed_author(test_db_session, 773601)
        judge = await seed_judge(test_db_session, 773602, nation=True)
        order = await make_order(
            test_db_session, author, nation=nation, judge=judge
        )

        view = await OrderService.write_verdict(
            test_db_session,
            player_id=judge.id,
            number=order.number,
            **VALID_VERDICT,
        )
        assert view.verdict_title == VALID_VERDICT["title"]

        await test_db_session.refresh(order)
        assert order.verdict_at is not None
        assert (
            await test_db_session.scalar(
                select(func.count()).select_from(BotOutbox)
            )
            == 0
        )
