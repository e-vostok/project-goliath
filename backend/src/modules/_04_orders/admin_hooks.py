"""
Admin hooks of module 04_orders (Spec 5.7).

- State view ``"04_orders"``: counts total and per derived stage, the
  overdue count, the unassigned count and the oldest unassigned age in
  minutes, the worker mode (``RUNNING``/``STOPPED``) and the moment of
  its last finished pass, plus the overdue orders list
  ``[{number, judge_vk_user_id, deadline_at}]`` (up to 50). The judge's
  ``vk_user_id`` lives **only here** — the admin endpoints are for the
  administrator alone, so INV-O5 relaxes just for this view (Spec 5.7).
  Times are ``YYYY-MM-DD HH:MM:SS`` strings in ``tick.tick_timezone``
  via ``format_game_time``.
- Reset ``"04_orders"``: deletes every order (INV-O14); players and
  ratings live in 00_core and survive — numbering restarts at 1 because
  the number is ``max(number) + 1`` of an empty table.

``register_orders_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.config_schema import CoreConfig
from modules._00_core.service import PlayerService
from modules._00_core.tick_schedule import format_game_time
from modules._04_orders.models import Order, OrderStage
from modules._04_orders.worker import get_last_pass_at, get_worker_mode

MODULE_SLUG = "04_orders"
OVERDUE_LIST_CAP = 50


def _aware(moment: datetime) -> datetime:
    """Naive datetimes are read as UTC (storage convention)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def orders_state_view(session: AsyncSession) -> dict:
    """Read-only JSON snapshot of the orders world (Spec 5.7)."""
    tz = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    ).tick.tick_timezone
    now = datetime.now(timezone.utc)

    total = (
        await session.execute(select(func.count()).select_from(Order))
    ).scalar_one()

    # Derived stages (D4): SUBMITTED = no judge, DISTRIBUTED = judge
    # without verdict, VERDICT = verdict written.
    stage_rows = await session.execute(
        select(
            func.count().filter(Order.verdict_at.is_not(None)),
            func.count().filter(
                Order.judge_player_id.is_not(None),
                Order.verdict_at.is_(None),
            ),
            func.count().filter(Order.judge_player_id.is_(None)),
        ).select_from(Order)
    )
    verdicts, distributed, submitted = stage_rows.one()

    overdue_rows = await session.execute(
        select(Order.number, Order.deadline_at, Order.judge_player_id)
        .where(
            Order.verdict_at.is_(None),
            Order.deadline_at.is_not(None),
            Order.deadline_at < now,
        )
        .order_by(Order.deadline_at)
    )
    overdue_all = overdue_rows.all()

    # The judge's VK id is resolved through the core service — the only
    # view allowed to expose it (Spec 5.7).
    judge_vk_ids = await PlayerService.vk_user_ids(
        session, {row[2] for row in overdue_all if row[2] is not None}
    )

    oldest_unassigned_at = (
        await session.execute(
            select(func.min(Order.submitted_at)).where(
                Order.judge_player_id.is_(None)
            )
        )
    ).scalar_one_or_none()

    last_pass_at = get_last_pass_at()

    return {
        "orders_total": total,
        "worker_mode": get_worker_mode().value,
        "last_pass_at": (
            None
            if last_pass_at is None
            else format_game_time(last_pass_at, tz)
        ),
        "stages": {
            OrderStage.SUBMITTED.value: submitted,
            OrderStage.DISTRIBUTED.value: distributed,
            OrderStage.VERDICT.value: verdicts,
        },
        "overdue_total": len(overdue_all),
        "unassigned_total": submitted,
        "oldest_unassigned_age_minutes": (
            None
            if oldest_unassigned_at is None
            else int(
                (now - _aware(oldest_unassigned_at)).total_seconds() // 60
            )
        ),
        "overdue_orders": [
            {
                "number": number,
                "judge_vk_user_id": judge_vk_ids.get(judge_player_id),
                "deadline_at": format_game_time(deadline_at, tz),
            }
            for number, deadline_at, judge_player_id in overdue_all[
                :OVERDUE_LIST_CAP
            ]
        ],
        "overdue_truncated": len(overdue_all) > OVERDUE_LIST_CAP,
    }


async def orders_reset(session: AsyncSession) -> None:
    """
    Wipe all orders (INV-O14). The caller owns the transaction — this
    hook never commits. Numbering restarts at 1 on the empty table.
    """
    await session.execute(delete(Order))


def register_orders_admin_hooks() -> None:
    """Register the state view and reset; safe on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, orders_state_view)
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, orders_reset)
