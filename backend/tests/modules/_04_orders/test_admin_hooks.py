"""
Admin-hook tests of module 04_orders (Spec 5.7, INV-O14).

The hooks are exercised through the AdminRegistry registrations the
real ``register_orders_admin_hooks()`` installs — the same path the
admin router takes — against the real in-memory DB.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from core.admin.registry import AdminRegistry
from modules._04_orders.admin_hooks import (
    MODULE_SLUG,
    register_orders_admin_hooks,
)
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import PlayerFactory, make_order, utcnow
from tests.modules._04_orders.conftest import seed_author

_VALID = {
    "title": "Приказ о наступлении",
    "summary": "Атаковать укреплённый пункт на рассвете.",
    "article_url": "https://vk.com/@offensive-order",
}


async def test_reset_empties_orders_and_restarts_numbering(
    test_db_session, orders_started
):
    """INV-O14: the reset hook wipes every order; the next number
    is 1 again because ``number = max(number) + 1`` of the empty table."""
    register_orders_admin_hooks()
    player, nation = await seed_author(test_db_session, 770401)
    for _ in range(2):
        outcome = await OrderService.submit(
            test_db_session,
            player_id=player.id,
            client_request_id=str(uuid.uuid4()),
            **_VALID,
        )
    assert outcome.view.number == 2

    hook = AdminRegistry.get_reset_hooks()[MODULE_SLUG]
    await hook(test_db_session)

    count = await test_db_session.scalar(
        select(func.count()).select_from(Order)
    )
    assert count == 0

    outcome = await OrderService.submit(
        test_db_session,
        player_id=player.id,
        client_request_id=str(uuid.uuid4()),
        **_VALID,
    )
    assert outcome.view.number == 1


async def test_state_view_counts_and_overdue_judge_vk(
    test_db_session, orders_started
):
    """The state view reports per-stage counts and overdue rows; the
    judge's ``vk_user_id`` rides along in the overdue entries — the
    only place where a judge is identifiable (Spec 5.7)."""
    register_orders_admin_hooks()
    author, nation = await seed_author(test_db_session, 770402)
    judge = PlayerFactory.build(vk_user_id=770403, nations=[])
    test_db_session.add(judge)
    await test_db_session.flush()

    now = utcnow()
    # One SUBMITTED, one DISTRIBUTED-and-overdue, one VERDICT.
    await make_order(
        test_db_session, author, nation=nation, submitted_at=now
    )
    await make_order(
        test_db_session,
        author,
        nation=nation,
        judge=judge,
        submitted_at=now - timedelta(hours=80),
    )
    await make_order(
        test_db_session,
        author,
        nation=nation,
        judge=judge,
        submitted_at=now - timedelta(hours=1),
        verdict_at=now,
    )

    hook = AdminRegistry.get_state_view_hooks()[MODULE_SLUG]
    view = await hook(test_db_session)
    json.dumps(view)

    assert view["orders_total"] == 3
    assert view["stages"] == {
        "SUBMITTED": 1,
        "DISTRIBUTED": 1,
        "VERDICT": 1,
    }
    assert view["overdue_total"] == 1
    assert view["unassigned_total"] == 1
    assert view["oldest_unassigned_age_minutes"] >= 0
    assert [entry["number"] for entry in view["overdue_orders"]] == [2]
    assert set(view["overdue_orders"][0]) == {
        "number",
        "judge_vk_user_id",
        "deadline_at",
    }
    assert view["overdue_orders"][0]["judge_vk_user_id"] == 770403
