"""
Admin hooks of module 04_orders (Spec 5.7).

- State view ``"04_orders"``: counts total and per derived stage, the
  overdue count, the unassigned count and the oldest unassigned age in
  minutes, the worker mode (``RUNNING``/``STOPPED``) and the moment of
  its last finished pass, plus the overdue orders list
  ``[{number, judge_vk_user_id, deadline_at}]`` (up to 50) and the
  assigned orders list ``[{number, author_vk_user_id,
  judge_vk_user_id, judge_nation_name, distributed_at, deadline_at,
  overdue}]`` — every judged-but-undecided order, newest number first,
  up to 50 (``assigned_truncated`` flags the rest). The judge's
  ``vk_user_id`` lives **only here** — the admin endpoints are for the
  administrator alone, so INV-O5 relaxes just for this view (Spec 5.7).
  Times are ``YYYY-MM-DD HH:MM:SS`` strings in ``tick.tick_timezone``
  via ``format_game_time``.
- Reset ``"04_orders"``: deletes every order (INV-O14); players and
  ratings live in 00_core and survive — numbering restarts at 1 because
  the number is ``max(number) + 1`` of an empty table.
- Player delete ``"04_orders.player_delete"``: under the same module
  advisory lock as submit/distribute/write_verdict — (i) orders where
  the player is the judge and no verdict exists return to the waiting
  queue (the five assignment columns become NULL, so the row is a clean
  SUBMITTED and the worker assigns it again); (ii) orders the player
  authored are deleted together with their verdict column group;
  (iii) orders where the player is the judge and a verdict exists are
  deleted too — the schema cannot keep a verdict without its judge
  (``ck_orders_verdict_needs_judge``). Runs inside
  ``PlayerService.delete_player``'s transaction — a raise aborts the
  whole deletion (no per-hook savepoint).
- Player preview ``"04_orders"``: returns ``{"orders_author",
  "orders_judge_undecided", "orders_judge_decided"}`` counts for the
  admin delete-preview; read-only.

``register_orders_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.config_schema import CoreConfig
from modules._00_core.hooks import register_player_delete_hook
from modules._00_core.service import PlayerService
from modules._00_core.tick_schedule import format_game_time
from modules._04_orders.models import Order, OrderStage, is_overdue
from modules._04_orders.service import ORDERS_ADVISORY_LOCK_KEY
from modules._04_orders.worker import get_last_pass_at, get_worker_mode

MODULE_SLUG = "04_orders"
OVERDUE_LIST_CAP = 50
ASSIGNED_LIST_CAP = 50


def _aware(moment: datetime) -> datetime:
    """Naive datetimes are read as UTC (storage convention)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def orders_state_view(session: AsyncSession) -> dict:
    """Read-only JSON snapshot of the orders world (Spec 5.7)."""
    tz = CoreConfig.from_yaml(CoreConfig.get_default_config_path()).tick.tick_timezone
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

    assigned_rows = await session.execute(
        select(Order)
        .where(
            Order.judge_player_id.is_not(None),
            Order.verdict_at.is_(None),
        )
        .order_by(Order.number.desc())
    )
    assigned_all = assigned_rows.scalars().all()

    # Author and judge identities (VK id, nation name) resolve through
    # the core read path — never through direct table reads (INV-O7).
    player_rows = {
        row.player_id: row for row in await PlayerService.list_for_registry(session)
    }

    def _player_field(player_id: str, field: str):
        row = player_rows.get(player_id)
        return getattr(row, field) if row is not None else None

    oldest_unassigned_at = (
        await session.execute(
            select(func.min(Order.submitted_at)).where(Order.judge_player_id.is_(None))
        )
    ).scalar_one_or_none()

    last_pass_at = get_last_pass_at()

    return {
        "orders_total": total,
        "worker_mode": get_worker_mode().value,
        "last_pass_at": (
            None if last_pass_at is None else format_game_time(last_pass_at, tz)
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
            else int((now - _aware(oldest_unassigned_at)).total_seconds() // 60)
        ),
        "overdue_orders": [
            {
                "number": number,
                "judge_vk_user_id": judge_vk_ids.get(judge_player_id),
                "deadline_at": format_game_time(deadline_at, tz),
            }
            for number, deadline_at, judge_player_id in overdue_all[:OVERDUE_LIST_CAP]
        ],
        "overdue_truncated": len(overdue_all) > OVERDUE_LIST_CAP,
        "assigned_orders": [
            {
                "number": order.number,
                "author_vk_user_id": _player_field(
                    order.author_player_id, "vk_user_id"
                ),
                "judge_vk_user_id": _player_field(order.judge_player_id, "vk_user_id"),
                "judge_nation_name": _player_field(
                    order.judge_player_id, "nation_name"
                ),
                "distributed_at": format_game_time(order.distributed_at, tz),
                "deadline_at": format_game_time(order.deadline_at, tz),
                "overdue": is_overdue(order, now),
            }
            for order in assigned_all[:ASSIGNED_LIST_CAP]
        ],
        "assigned_truncated": len(assigned_all) > ASSIGNED_LIST_CAP,
    }


async def orders_reset(session: AsyncSession) -> None:
    """
    Wipe all orders (INV-O14). The caller owns the transaction — this
    hook never commits. Numbering restarts at 1 on the empty table.
    """
    await session.execute(delete(Order))


async def orders_player_delete_preview(session: AsyncSession, player_id: str) -> dict:
    """Counts of this player's orders by role for the delete-preview."""
    authored = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(Order.author_player_id == player_id)
        )
    ).scalar_one()
    judged_undecided = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.judge_player_id == player_id,
                Order.verdict_at.is_(None),
            )
        )
    ).scalar_one()
    judged_decided = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.judge_player_id == player_id,
                Order.verdict_at.is_not(None),
            )
        )
    ).scalar_one()
    return {
        "orders_author": authored,
        "orders_judge_undecided": judged_undecided,
        "orders_judge_decided": judged_decided,
    }


async def orders_delete_player(session: AsyncSession, player_id: str) -> None:
    """
    Remove this module's rows of one player (admin player deletion).

    Runs under the module advisory lock — the same key serializing
    submit/distribute/write_verdict on PostgreSQL, a no-op on SQLite —
    so a deletion cannot race an assignment or a verdict. Three steps:

    1. Orders where the player is the judge with no verdict yet go back
       to the waiting queue: the five assignment columns become NULL
       together (the all-or-none CHECK is satisfied), the row is a clean
       SUBMITTED and the worker will assign a new judge — the author
       keeps a live order.
    2. Orders the player authored are deleted with their verdict column
       group.
    3. Orders where the player is the judge and a verdict exists are
       deleted — the schema cannot keep a verdict without its judge
       (``ck_orders_verdict_needs_judge``).

    Explicit statements, not FK cascade: SQLite may run without enforced
    foreign keys. Inside the caller's transaction; never commits, and a
    raise rolls the whole player deletion back.
    """
    if session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": ORDERS_ADVISORY_LOCK_KEY},
        )

    await session.execute(
        update(Order)
        .where(
            Order.judge_player_id == player_id,
            Order.verdict_at.is_(None),
        )
        .values(
            judge_player_id=None,
            distributed_at=None,
            deadline_at=None,
            reminder_at=None,
            reminder_sent_at=None,
        )
    )
    await session.execute(delete(Order).where(Order.author_player_id == player_id))
    await session.execute(delete(Order).where(Order.judge_player_id == player_id))


def register_orders_admin_hooks() -> None:
    """Register the admin hooks; safe to call on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, orders_state_view)
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, orders_reset)
    if MODULE_SLUG not in AdminRegistry.get_player_preview_hooks():
        AdminRegistry.register_player_preview(MODULE_SLUG, orders_player_delete_preview)
    register_player_delete_hook(f"{MODULE_SLUG}.player_delete", orders_delete_player)
