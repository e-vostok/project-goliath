"""
HTTP routes of module 04_orders (Spec 5.1).

Endpoints under ``/api/v1/orders`` behind the shared Bearer JWT
dependency: the field rules for the composer, order submission (201 on
a new order, 200 on an idempotent repeat of the same
``client_request_id``, INV-O9), the judge's assigned queue, the
order's public detail and the verdict write. All responses are
``Cache-Control: no-store`` —
player data is never cached. The order number in the path is an
integer >= 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Player
from modules._04_orders.dto import (
    AssignedOrderDTO,
    AssignedOrdersDTO,
    NationMarkDTO,
    OrderCreateRequest,
    OrderDetailDTO,
    OrderRulesDTO,
    VerdictCreateRequest,
    VerdictDTO,
)
from modules._04_orders.service import (
    AssignedOrderView,
    OrderDetailView,
    OrderService,
)
from modules._04_orders.worker import request_orders_wake

router = APIRouter(prefix="/api/v1/orders")


def _nation_mark(view) -> NationMarkDTO:
    """The nation snapshot of a service view as the wire mark.

    ``flag_url`` stays null until unit 5 (the uploaded flag, INV-16).
    """
    return NationMarkDTO(
        name=view.nation_name,
        color=view.nation_color,
        short_name=view.nation_short_name,
        flag_url=None,
    )


def _detail_dto(view: OrderDetailView) -> OrderDetailDTO:
    """Service view -> wire DTO (the nation snapshot as NationMarkDTO)."""
    return OrderDetailDTO(
        number=view.number,
        nation=_nation_mark(view),
        title=view.title,
        summary=view.summary,
        article_url=view.article_url,
        distributed=view.distributed,
        verdict=(
            None
            if view.verdict_title is None
            else VerdictDTO(
                title=view.verdict_title,
                summary=view.verdict_summary,
                article_url=view.verdict_url,
            )
        ),
        overdue=view.overdue,
        can_write_verdict=view.can_write_verdict,
    )


def _deadline_text(moment: datetime) -> str:
    """``DD.MM.YYYY HH:MM`` in tick.tick_timezone (Spec 5.2)."""
    tz = CoreConfig.from_yaml(CoreConfig.get_default_config_path()).tick.tick_timezone
    # Naive datetimes are read as UTC (SQLite returns naive values even
    # for timezone=True columns — the same convention as admin_hooks).
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(ZoneInfo(tz)).strftime("%d.%m.%Y %H:%M")


def _assigned_dto(view: AssignedOrderView) -> AssignedOrderDTO:
    """Service view -> wire DTO (the nation snapshot as NationMarkDTO)."""
    return AssignedOrderDTO(
        number=view.number,
        nation=_nation_mark(view),
        title=view.title,
        summary=view.summary,
        article_url=view.article_url,
        deadline_text=_deadline_text(view.deadline_at),
        overdue=view.overdue,
    )


@router.get("/rules", response_model=OrderRulesDTO)
async def get_order_rules(
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> OrderRulesDTO:
    """Spec 5.1 — the field limits plus the caller's unresolved count."""
    response.headers["Cache-Control"] = "no-store"
    # Local import: startup.py holds the config loaded once at boot.
    from modules._04_orders.startup import get_orders_config

    config = get_orders_config()
    unresolved = await OrderService.unresolved_count(session, player_id=player.id)
    return OrderRulesDTO(
        title_min_length=config.limits.title_min_length,
        title_max_length=config.limits.title_max_length,
        summary_min_length=config.limits.summary_min_length,
        summary_max_length=config.limits.summary_max_length,
        url_max_length=config.limits.url_max_length,
        max_unresolved_orders=config.author.max_unresolved_orders,
        unresolved_orders=unresolved,
    )


@router.post("", response_model=OrderDetailDTO, status_code=201)
async def submit_order(
    body: OrderCreateRequest,
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailDTO:
    """Spec 5.1 — accept an order; 201 new, 200 idempotent repeat."""
    response.headers["Cache-Control"] = "no-store"
    outcome = await OrderService.submit(
        session,
        player_id=player.id,
        client_request_id=str(body.client_request_id),
        title=body.title,
        summary=body.summary,
        article_url=body.article_url,
    )
    await session.commit()
    # Spec 2.3: a fresh order may wait for a judge — wake the worker;
    # a no-op while none runs.
    request_orders_wake()
    if not outcome.created:
        response.status_code = 200
    return _detail_dto(outcome.view)


@router.get("/assigned", response_model=AssignedOrdersDTO)
async def list_assigned_orders(
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> AssignedOrdersDTO:
    """
    Spec 5.1 — the caller's orders awaiting their verdict, soonest
    deadline first. Registered before ``/{number}`` so the literal wins.
    """
    response.headers["Cache-Control"] = "no-store"
    views = await OrderService.list_assigned(session, player_id=player.id)
    return AssignedOrdersDTO(items=[_assigned_dto(view) for view in views])


@router.post("/{number}/verdict", response_model=OrderDetailDTO, status_code=201)
async def write_verdict(
    number: Annotated[int, Path(ge=1)],
    body: VerdictCreateRequest,
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailDTO:
    """
    Spec 5.1 — the assigned judge writes the verdict; every other
    caller gets one and the same ``ORDER_VERDICT_FORBIDDEN`` (INV-O5).
    """
    response.headers["Cache-Control"] = "no-store"
    view = await OrderService.write_verdict(
        session,
        player_id=player.id,
        number=number,
        title=body.title,
        summary=body.summary,
        article_url=body.article_url,
    )
    await session.commit()
    # Spec 2.3: a verdict frees a judge's load slot — wake the worker.
    request_orders_wake()
    return _detail_dto(view)


@router.get("/{number}", response_model=OrderDetailDTO)
async def get_order(
    number: Annotated[int, Path(ge=1)],
    response: Response,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailDTO:
    """Spec 5.1 — one order's public detail; 404 ``ORDER_NOT_FOUND``."""
    response.headers["Cache-Control"] = "no-store"
    view = await OrderService.get_detail(
        session, number=number, viewer_player_id=player.id
    )
    return _detail_dto(view)
