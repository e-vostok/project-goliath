"""
``GET /orders/mine`` — the caller's own order numbers by the CURRENT
``nation_id`` (0.14.0 unit 5).

An order keeps the nation snapshot of the submission (INV-O6): after
the nation is renamed the snapshot ``nation_short_name`` no longer
matches, so a name-based filter would drop the player's own orders.
The endpoint answers numbers only — matched on ``nation_id`` — and an
empty list when the caller owns no nation.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.db import get_session
from main import app
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author

ORDERS_URL = "/api/v1/orders"
NATIONS_ME_URL = "/api/v1/nations/me"

VALID_ORDER = {
    "title": "Приказ о наступлении",
    "summary": "Перейти в наступление на рассвете следующего дня.",
    "article_url": "https://vk.com/@attack-order",
}


@pytest_asyncio.fixture
async def orders_client(session_factory):
    """HTTP client where every request opens its own session on the
    test engine — the production shape (see test_integration.py)."""

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


class TestMyOrders:
    async def test_mine_follows_nation_id_through_a_rename(
        self, orders_client, session_factory, orders_bot_started
    ):
        """Submit, rename the nation's short name, ``/mine`` still
        answers the order's number — and only the caller's own."""
        async with session_factory() as session:
            author, _nation = await seed_author(
                session, 882001, nation_name="Старое Имя", nation_color="#112233"
            )
            other, _other_nation = await seed_author(
                session,
                882002,
                nation_name="Чужое Государство",
                nation_color="#445566",
            )
            await session.commit()
            author_id, other_id = author.id, other.id

        headers = bearer_headers(author_id)
        submit = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": str(uuid.uuid4())},
            headers=headers,
        )
        assert submit.status_code == 201
        assert submit.json()["number"] == 1

        # A second nation submits its own order — it must not leak
        # into the caller's list.
        other_submit = await orders_client.post(
            ORDERS_URL,
            json={**VALID_ORDER, "client_request_id": str(uuid.uuid4())},
            headers=bearer_headers(other_id),
        )
        assert other_submit.status_code == 201
        assert other_submit.json()["number"] == 2

        # Rename the author's nation — the order's snapshot keeps the
        # old short name (INV-O6), the filter must not.
        rename = await orders_client.patch(
            NATIONS_ME_URL, json={"short_name": "Новое"}, headers=headers
        )
        assert rename.status_code == 200
        assert rename.json()["short_name"] == "Новое"

        mine = await orders_client.get(f"{ORDERS_URL}/mine", headers=headers)
        assert mine.status_code == 200
        assert mine.headers["cache-control"] == "no-store"
        assert mine.json() == {"items": [{"number": 1}]}
