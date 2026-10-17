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
from main import app
from modules._04_orders.admin_hooks import (
    MODULE_SLUG,
    register_orders_admin_hooks,
)
from modules._04_orders.models import Order
from modules._04_orders.service import OrderService
from tests.fixtures.factories import PlayerFactory, make_order, utcnow
from tests.modules._03_registry.conftest import bearer_headers
from tests.modules._04_orders.conftest import seed_author, seed_judge

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


async def test_state_view_assigned_orders_lists_judged_undecided(
    test_db_session, orders_started
):
    """``assigned_orders`` lists every judged-but-undecided order,
    newest number first, with the author's and judge's VK ids and the
    judge's nation name (None for a judge without a nation) — the
    admin-only relaxation of INV-O5 (Spec 5.7)."""
    register_orders_admin_hooks()
    author, nation = await seed_author(test_db_session, 770410)
    judge_with = await seed_judge(test_db_session, 770411, nation=True)
    judge_without = await seed_judge(test_db_session, 770412)

    now = utcnow()
    # SUBMITTED (no judge) and VERDICT rows never enter the list.
    await make_order(test_db_session, author, nation=nation)
    await make_order(
        test_db_session,
        author,
        nation=nation,
        judge=judge_with,
        submitted_at=now - timedelta(hours=80),
    )
    await make_order(
        test_db_session,
        author,
        nation=nation,
        judge=judge_without,
        submitted_at=now,
    )
    await make_order(
        test_db_session,
        author,
        nation=nation,
        judge=judge_with,
        submitted_at=now - timedelta(hours=2),
        verdict_at=now,
    )

    hook = AdminRegistry.get_state_view_hooks()[MODULE_SLUG]
    view = await hook(test_db_session)
    json.dumps(view)

    assert view["assigned_truncated"] is False
    assert [entry["number"] for entry in view["assigned_orders"]] == [3, 2]
    fresh, overdue_entry = view["assigned_orders"]
    assert set(fresh) == {
        "number",
        "author_vk_user_id",
        "judge_vk_user_id",
        "judge_nation_name",
        "distributed_at",
        "deadline_at",
        "overdue",
    }
    assert fresh["author_vk_user_id"] == 770410
    assert fresh["judge_vk_user_id"] == 770412
    assert fresh["judge_nation_name"] is None
    assert fresh["overdue"] is False
    assert isinstance(fresh["distributed_at"], str)
    assert isinstance(fresh["deadline_at"], str)
    assert overdue_entry["judge_vk_user_id"] == 770411
    assert overdue_entry["judge_nation_name"] == "Судейство 770411"
    assert overdue_entry["overdue"] is True


async def test_state_view_assigned_orders_caps_at_fifty(
    test_db_session, orders_started
):
    """Over 50 judged-undecided orders: the list keeps the 50 highest
    numbers and ``assigned_truncated`` flags the rest (Spec 5.7)."""
    register_orders_admin_hooks()
    author, nation = await seed_author(test_db_session, 770420)
    judge = await seed_judge(test_db_session, 770421)
    for _ in range(51):
        await make_order(
            test_db_session, author, nation=nation, judge=judge
        )

    hook = AdminRegistry.get_state_view_hooks()[MODULE_SLUG]
    view = await hook(test_db_session)

    assert view["assigned_truncated"] is True
    assert len(view["assigned_orders"]) == 50
    assert view["assigned_orders"][0]["number"] == 51
    assert view["assigned_orders"][-1]["number"] == 2


def _schema_nodes(node: dict | None, components: dict, seen: set[str]):
    """Yield a response schema and every nested / ``$ref``'d component."""
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in seen or name not in components:
            return
        seen.add(name)
        yield components[name]
        yield from _schema_nodes(components[name], components, seen)
        return
    yield node
    nested = list(node.get("properties", {}).values())
    for key in ("allOf", "anyOf", "oneOf"):
        nested.extend(node.get(key, []))
    if isinstance(node.get("items"), dict):
        nested.append(node["items"])
    for sub in nested:
        yield from _schema_nodes(sub, components, seen)


def test_orders_openapi_responses_have_no_judge_field():
    """INV-O5 stands outside the admin panel: no ``/api/v1/orders/*``
    response model — nested DTOs included — names a field containing
    ``judge``. The admin state view is the only judge-visible surface
    (Spec 5.7)."""
    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    offenders = []
    for path, ops in schema["paths"].items():
        if not path.startswith("/api/v1/orders"):
            continue
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            for status, response in op.get("responses", {}).items():
                for media in response.get("content", {}).values():
                    for node in _schema_nodes(
                        media.get("schema"), components, set()
                    ):
                        for field_name in node.get("properties", {}):
                            if "judge" in field_name.lower():
                                offenders.append(
                                    f"{method.upper()} {path} {status}: "
                                    f"{field_name}"
                                )
    assert offenders == []


async def test_admin_state_view_stays_admin_only(
    client, test_db_session, orders_started, monkeypatch
):
    """The endpoint that carries the judge fields stays behind
    ``require_admin``: an authenticated non-admin gets the existing
    403 ADMIN_REQUIRED."""
    monkeypatch.setenv("ADMIN_VK_USER_IDS", "424242")
    player = PlayerFactory.build(vk_user_id=770430, nations=[])
    test_db_session.add(player)
    await test_db_session.flush()

    response = await client.get(
        "/api/v1/admin/state", headers=bearer_headers(player.id)
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ADMIN_REQUIRED"
