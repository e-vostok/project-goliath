"""
HTTP routes of module 04_orders (Spec 5.1).

Endpoints under ``/api/v1/orders`` behind the shared Bearer JWT
dependency: the field rules for the composer, order submission (201 on
a new order, 200 on an idempotent repeat of the same
``client_request_id``, INV-O9) and the order's public detail. All
responses are ``Cache-Control: no-store`` — player data is never cached.
The order number in the path is an integer >= 1.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from modules._00_core.models import Player
from modules._04_orders.dto import (
    NationMarkDTO,
    OrderCreateRequest,
    OrderDetailDTO,
    OrderRulesDTO,
    VerdictDTO,
)
from modules._04_orders.service import OrderDetailView, OrderService

router = APIRouter(prefix="/api/v1/orders")


def _detail_dto(view: OrderDetailView) -> OrderDetailDTO:
    """Service view -> wire DTO (the nation snapshot as NationMarkDTO)."""
    return OrderDetailDTO(
        number=view.number,
        nation=NationMarkDTO(
            name=view.nation_name, color=view.nation_color
        ),
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
    unresolved = await OrderService.unresolved_count(
        session, player_id=player.id
    )
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
    if not outcome.created:
        response.status_code = 200
    return _detail_dto(outcome.view)


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
