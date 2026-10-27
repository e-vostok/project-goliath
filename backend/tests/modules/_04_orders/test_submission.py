"""
Module 04_orders submission tests (Spec 5.1–5.3, INV-O6/O9/O15).

Real in-memory DB, rows seeded through the shared factories
(Anti-Mock Guard) — nothing is mocked. ``orders_started`` runs the
real ``startup_orders()`` so the service reads the shipped config.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from modules._00_core.config_schema import CoreConfig
from modules._00_core.service import NationService
from modules._04_orders.exceptions import (
    OrderAuthorLimitReachedError,
    OrderNationRequiredError,
    OrderUrlInvalidError,
)
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import (
    PlayerFactory,
    make_order,
    utcnow,
)
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
ORDERS_URL = "/api/v1/orders"

VALID_TITLE = "Приказ о перебазировании"
VALID_SUMMARY = "Перевести вторую армию к северной границе."
VALID_URL = "https://vk.com/@order-one"


def _body(request_id: str | None = None) -> dict:
    return {
        "title": VALID_TITLE,
        "summary": VALID_SUMMARY,
        "article_url": VALID_URL,
        "client_request_id": request_id or str(uuid.uuid4()),
    }


class TestSubmitService:
    """``OrderService.submit`` — Spec 5.1 check order on a real DB."""

    async def test_submit_stores_number_and_nation_snapshot(
        self, test_db_session, orders_started
    ):
        player, nation = await seed_author(
            test_db_session, 770001, nation_name="Северная Лига"
        )

        outcome = await OrderService.submit(
            test_db_session,
            player_id=player.id,
            client_request_id=str(uuid.uuid4()),
            title=VALID_TITLE,
            summary=VALID_SUMMARY,
            article_url=VALID_URL,
        )

        assert outcome.created is True
        assert outcome.view.number == 1
        row = (await test_db_session.execute(select(Order))).scalar_one()
        assert row.number == 1
        assert row.author_player_id == player.id
        # INV-O6: the snapshot columns carry the nation's identity —
        # full name, colour and short name at submission.
        assert row.nation_id == nation.id
        assert row.nation_name == "Северная Лига"
        assert row.nation_color == nation.color_hex
        assert row.nation_short_name == nation.short_name
        assert row.submitted_at is not None
        assert row.judge_player_id is None

    async def test_snapshot_survives_nation_rename(
        self, test_db_session, orders_started
    ):
        player, nation = await seed_author(
            test_db_session, 770002, nation_name="Старое Имя"
        )
        old_short_name = nation.short_name
        await OrderService.submit(
            test_db_session,
            player_id=player.id,
            client_request_id=str(uuid.uuid4()),
            title=VALID_TITLE,
            summary=VALID_SUMMARY,
            article_url=VALID_URL,
        )

        # Rename, recolour and re-short-name through the real update path.
        await NationService.update(
            test_db_session,
            nation.id,
            name="Новое Имя",
            color_hex="#0000FF",
            short_name="НовИмя",
            config=CORE_CONFIG,
        )
        await test_db_session.flush()

        view = await OrderService.get_detail(
            test_db_session, number=1, viewer_player_id=player.id
        )
        assert view.nation_name == "Старое Имя"
        assert view.nation_color == "#336699"
        # The frozen short name survives the rename too.
        assert view.nation_short_name == old_short_name

    async def test_submit_without_nation_refused(self, test_db_session, orders_started):
        player = PlayerFactory.build(vk_user_id=770003, nations=[])
        test_db_session.add(player)
        await test_db_session.flush()

        with pytest.raises(OrderNationRequiredError) as exc_info:
            await OrderService.submit(
                test_db_session,
                player_id=player.id,
                client_request_id=str(uuid.uuid4()),
                title=VALID_TITLE,
                summary=VALID_SUMMARY,
                article_url=VALID_URL,
            )
        assert exc_info.value.code == "ORDER_NATION_REQUIRED"

    async def test_submit_foreign_host_url_refused(
        self, test_db_session, orders_started
    ):
        player, _ = await seed_author(test_db_session, 770004)

        with pytest.raises(OrderUrlInvalidError) as exc_info:
            await OrderService.submit(
                test_db_session,
                player_id=player.id,
                client_request_id=str(uuid.uuid4()),
                title=VALID_TITLE,
                summary=VALID_SUMMARY,
                article_url="https://evil.example.com/@order-1",
            )
        assert exc_info.value.code == "ORDER_URL_INVALID"

    async def test_author_limit_and_verdict_frees_slot(
        self, test_db_session, orders_started
    ):
        """Sixth order at the 5-order limit is refused; a verdict
        written on one of them frees the slot (INV-O15)."""
        author, nation = await seed_author(test_db_session, 770105)
        judge = PlayerFactory.build(vk_user_id=770199, nations=[])
        test_db_session.add(judge)
        await test_db_session.flush()
        written = [
            await make_order(test_db_session, author, nation=nation, judge=judge)
            for _ in range(5)
        ]

        with pytest.raises(OrderAuthorLimitReachedError) as exc_info:
            await OrderService.submit(
                test_db_session,
                player_id=author.id,
                client_request_id=str(uuid.uuid4()),
                title=VALID_TITLE,
                summary=VALID_SUMMARY,
                article_url=VALID_URL,
            )
        assert exc_info.value.code == "ORDER_AUTHOR_LIMIT_REACHED"

        # A verdict is written directly on the row (the verdict
        # endpoint arrives with Issue 7).
        first = written[0]
        first.verdict_title = "Отклонено"
        first.verdict_summary = "Вердикт по первому приказу."
        first.verdict_url = "https://vk.com/@verdict-one"
        first.verdict_at = utcnow()
        await test_db_session.flush()

        outcome = await OrderService.submit(
            test_db_session,
            player_id=author.id,
            client_request_id=str(uuid.uuid4()),
            title=VALID_TITLE,
            summary=VALID_SUMMARY,
            article_url=VALID_URL,
        )
        assert outcome.created is True
        assert outcome.view.number == 6


class TestSubmitHttp:
    """The wire contract of ``POST /orders`` (Spec 5.1, 5.2)."""

    async def test_submit_then_repeat_returns_same_order(
        self, client, test_db_session, orders_started
    ):
        player, nation = await seed_author(test_db_session, 770201)
        headers = bearer_headers(player.id)
        request_id = str(uuid.uuid4())

        first = await client.post(ORDERS_URL, json=_body(request_id), headers=headers)
        assert first.status_code == 201
        assert first.headers["cache-control"] == "no-store"
        body = first.json()
        assert body == {
            "number": 1,
            "nation": {
                "name": nation.name,
                "color": nation.color_hex,
                "short_name": nation.short_name,
                "flag_url": None,
            },
            "title": VALID_TITLE,
            "summary": VALID_SUMMARY,
            "article_url": VALID_URL,
            "distributed": False,
            "verdict": None,
            "overdue": False,
            "can_write_verdict": False,
        }

        # INV-O9: the idempotent repeat answers 200 with the same order.
        repeat = await client.post(ORDERS_URL, json=_body(request_id), headers=headers)
        assert repeat.status_code == 200
        assert repeat.json() == body
        count = await test_db_session.scalar(select(func.count()).select_from(Order))
        assert count == 1

        detail = await client.get(f"{ORDERS_URL}/1", headers=headers)
        assert detail.status_code == 200
        assert detail.json() == body

        missing = await client.get(f"{ORDERS_URL}/99", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["code"] == "ORDER_NOT_FOUND"
