"""
HTTP admin API of module 04_orders (0.11.0 unit 10a).

Three endpoints under ``/api/v1/admin/orders``, every one gated by
``require_admin``:

- ``GET /`` — the panel's orders list: ``status`` filter
  (``all|waiting|assigned|decided``), a free ``search`` over the public
  number and the title, ``limit``/``offset`` paging; items carry the
  author-nation snapshot, the names the player-info hooks know and the
  judge's VK id — admin contour only, no player ever learns who the
  judge is (INV-O5).
- ``GET /{number}/judge-preview`` — read-only: the current judge, the
  picked one, the one ``blocker`` that would refuse the assignment
  (``ORDER_ALREADY_DECIDED`` / ``JUDGE_IS_AUTHOR`` / ``ALREADY_JUDGE``)
  and the ready Russian ``warnings`` — an unreachable judge (no nation
  and no bot consent), a rating below the threshold, a full pending
  queue; every threshold is read from the module config, never
  hard-coded.
- ``POST /{number}/judge`` — the assignment itself through
  ``OrderService.admin_assign_judge``, then one ``order.assign_judge``
  audit row in the same transaction before the commit; a refusal
  writes nothing. The answer is the order's list item.

Names resolve through the modules' player-info hooks — the
``display_name`` column of the panel's «Игроки» table — never through
foreign tables (INV-O7).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from core.admin.security import require_admin
from core.db import get_session
from modules._00_core.admin_service import AdminAuditService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import PlayerNotFoundError
from modules._00_core.models import Player
from modules._00_core.service import PlayerService
from modules._00_core.tick_schedule import format_game_time
from modules._02_bot.service import BotService
from modules._04_orders.exceptions import OrderNotFoundError
from modules._04_orders.models import Order, is_overdue
from modules._04_orders.service import OrderService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/orders")

AssignStatus = Literal["all", "waiting", "assigned", "decided"]


class AssignJudgeRequest(BaseModel):
    """``POST /{number}/judge`` body — the picked judge by VK id."""

    model_config = ConfigDict(extra="forbid")

    judge_vk_user_id: int


def _status_clause(status: AssignStatus):
    """The derived-stage predicate of a list filter value."""
    if status == "waiting":
        return Order.judge_player_id.is_(None)
    if status == "assigned":
        return and_(
            Order.judge_player_id.is_not(None),
            Order.verdict_at.is_(None),
        )
    if status == "decided":
        return Order.verdict_at.is_not(None)
    return None


def _status_of(order: Order) -> str:
    """The panel's status label of a row — the derived stage."""
    if order.verdict_at is not None:
        return "DECIDED"
    if order.judge_player_id is not None:
        return "AWAITING_VERDICT"
    return "NO_JUDGE"


def _list_item(
    order: Order,
    *,
    judge_vk_user_id: int | None,
    names: dict[str, str],
    tz: str,
    now: datetime,
) -> dict:
    """One list item — the answer shape of GET / and POST /{n}/judge."""
    return {
        "number": order.number,
        "title": order.title,
        "author_nation_short_name": order.nation_short_name,
        "author_name": names.get(order.author_player_id),
        "judge_vk_user_id": judge_vk_user_id,
        "judge_name": names.get(order.judge_player_id),
        "status": _status_of(order),
        "deadline_at": format_game_time(order.deadline_at, tz),
        "overdue": is_overdue(order, now),
    }


async def _display_names(
    session: AsyncSession, player_ids: set[str | None]
) -> dict[str, str]:
    """
    ``{player_id: display_name}`` merged from every module's
    player-info hook — the same names the panel's «Игроки» table
    shows. A failing hook is logged, its session work rolled back and
    its columns skipped, like ``core.admin.router`` does.
    """
    ids = [pid for pid in player_ids if pid is not None]
    if not ids:
        return {}
    names: dict[str, str] = {}
    for slug, (info_fn, _) in AdminRegistry.get_player_info_hooks().items():
        try:
            columns = await info_fn(session, ids)
        except Exception:
            logger.exception("Admin player-info hook failed for '%s'", slug)
            await session.rollback()
            continue
        for player_id, fields in (columns or {}).items():
            name = fields.get("display_name")
            if name is not None:
                names.setdefault(player_id, name)
    return names


async def _load_order(session: AsyncSession, number: int) -> Order:
    """The order row or 404 ORDER_NOT_FOUND."""
    order = (
        await session.execute(select(Order).where(Order.number == number))
    ).scalar_one_or_none()
    if order is None:
        raise OrderNotFoundError(number)
    return order


async def _player_row_by_vk(session: AsyncSession, vk_user_id: int):
    """The target's registry row or 404 PLAYER_NOT_FOUND (INV-O7)."""
    for row in await PlayerService.list_for_registry(session):
        if row.vk_user_id == vk_user_id:
            return row
    raise PlayerNotFoundError(f"vk_user_id={vk_user_id}")


def _tick_timezone() -> str:
    return CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    ).tick.tick_timezone


@router.get("")
async def list_orders(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    status: AssignStatus = "all",
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """
    The panel's «Приказы» list (0.11.0 unit 10a): one page of orders,
    newest public number first — ``{"items", "total"}``. ``status``
    filters the derived stage, ``search`` matches an exact number or a
    case-insensitive title substring (folded in Python like the
    players list — SQLite's ``lower()`` only folds ASCII).
    """
    stmt = select(Order).order_by(Order.number.desc())
    clause = _status_clause(status)
    if clause is not None:
        stmt = stmt.where(clause)
    rows_all = list((await session.execute(stmt)).scalars().all())

    text = (search or "").strip()
    if text:
        lowered = text.casefold()
        number_query = int(text) if text.isdigit() else None
        rows_all = [
            order
            for order in rows_all
            if (number_query is not None and order.number == number_query)
            or lowered in order.title.casefold()
        ]
    total = len(rows_all)
    page = rows_all[offset : offset + limit]

    names = await _display_names(
        session,
        {order.author_player_id for order in page}
        | {order.judge_player_id for order in page},
    )
    vk_ids = await PlayerService.vk_user_ids(
        session,
        {order.judge_player_id for order in page if order.judge_player_id},
    )
    tz = _tick_timezone()
    now = datetime.now(UTC)
    return {
        "items": [
            _list_item(
                order,
                judge_vk_user_id=vk_ids.get(order.judge_player_id),
                names=names,
                tz=tz,
                now=now,
            )
            for order in page
        ],
        "total": total,
    }


@router.get("/{number}/judge-preview")
async def judge_preview(
    number: Annotated[int, Path(ge=1)],
    judge_vk_user_id: int,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Read-only preview of ``POST /{number}/judge``: the current judge,
    the picked player, the one ``blocker`` the service would refuse
    with (the same order of checks) and the warnings the panel shows —
    an unreachable judge, a rating below ``judge.min_rating``, a
    pending queue at ``judge.max_pending_verdicts``. None of the
    warnings blocks the admin path — they only inform.
    """
    from modules._04_orders.startup import get_orders_config

    judge_cfg = get_orders_config().judge
    order = await _load_order(session, number)
    new_row = await _player_row_by_vk(session, judge_vk_user_id)

    names = await _display_names(
        session, {order.author_player_id, order.judge_player_id, new_row.player_id}
    )
    vk_ids = await PlayerService.vk_user_ids(
        session,
        {order.judge_player_id} if order.judge_player_id is not None else set(),
    )

    blocker = None
    if order.verdict_at is not None:
        blocker = "ORDER_ALREADY_DECIDED"
    elif new_row.player_id == order.author_player_id:
        blocker = "JUDGE_IS_AUTHOR"
    elif order.judge_player_id == new_row.player_id:
        blocker = "ALREADY_JUDGE"

    subject = names.get(new_row.player_id) or str(judge_vk_user_id)
    warnings: list[dict] = []
    if new_row.nation_id is None and not (
        await BotService.consented_player_ids(session, [new_row.player_id])
    ):
        warnings.append(
            {
                "code": "JUDGE_UNREACHABLE",
                "text": (
                    f"Игрок «{subject}» без государства и без согласия "
                    "на сообщения не узнает об этом приказе."
                ),
            }
        )
    if new_row.judge_rating < judge_cfg.min_rating:
        warnings.append(
            {
                "code": "JUDGE_RATING_BELOW",
                "text": (
                    f"Судейский рейтинг игрока «{subject}» — "
                    f"{new_row.judge_rating}, ниже порога "
                    f"{judge_cfg.min_rating}."
                ),
            }
        )
    pending = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.judge_player_id == new_row.player_id,
                Order.verdict_at.is_(None),
            )
        )
    ).scalar_one()
    if pending >= judge_cfg.max_pending_verdicts:
        warnings.append(
            {
                "code": "JUDGE_AT_PENDING_LIMIT",
                "text": (
                    f"У игрока «{subject}» уже {pending} приказов без "
                    f"вердикта — предел {judge_cfg.max_pending_verdicts}."
                ),
            }
        )

    current_judge = None
    if order.judge_player_id is not None:
        current_judge = {
            "vk_user_id": vk_ids.get(order.judge_player_id),
            "name": names.get(order.judge_player_id),
        }
    return {
        "current_judge": current_judge,
        "new_judge": {
            "vk_user_id": judge_vk_user_id,
            "name": names.get(new_row.player_id),
        },
        "blocker": blocker,
        "warnings": warnings,
    }


@router.post("/{number}/judge")
async def assign_judge(
    number: Annotated[int, Path(ge=1)],
    body: AssignJudgeRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Assign — or reassign — the order's judge (0.11.0 unit 10a).

    Unknown order -> 404 ORDER_NOT_FOUND; unknown player -> 404
    PLAYER_NOT_FOUND; then the service's own refusals keep their codes
    and write nothing. On success one ``order.assign_judge`` audit row
    lands in the same transaction before the commit: the summary is
    one Russian sentence, ``details`` carries ids only. The answer is
    the order's list item.
    """
    order = await _load_order(session, number)
    new_row = await _player_row_by_vk(session, body.judge_vk_user_id)

    # Names for the audit sentence — resolved before any write: a
    # hook's failure rolls the session back and must never take the
    # assignment with it.
    names = await _display_names(
        session, {order.author_player_id, order.judge_player_id, new_row.player_id}
    )

    outcome = await OrderService.admin_assign_judge(
        session, number, new_row.player_id
    )
    previous_judge_id = outcome.previous_judge_player_id

    new_name = names.get(new_row.player_id) or str(body.judge_vk_user_id)
    details = {
        "order_id": order.id,
        "previous_judge_player_id": previous_judge_id,
        "judge_player_id": new_row.player_id,
    }
    if previous_judge_id is None:
        summary = f"Приказу № {number} назначен судья {new_name}."
    else:
        previous_vk = (
            await PlayerService.vk_user_ids(session, {previous_judge_id})
        ).get(previous_judge_id)
        previous_name = names.get(previous_judge_id) or str(previous_vk)
        summary = (
            f"Судья приказа № {number} заменён: "
            f"{previous_name} → {new_name}."
        )
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="order.assign_judge",
        target_type="order",
        target_id=str(number),
        summary=summary,
        details=details,
    )
    # The item is built before the commit: commit expires the ORM
    # attributes, so the answer is materialized while they are loaded.
    item = _list_item(
        outcome.order,
        judge_vk_user_id=body.judge_vk_user_id,
        names=names,
        tz=_tick_timezone(),
        now=datetime.now(UTC),
    )
    await session.commit()
    return item
