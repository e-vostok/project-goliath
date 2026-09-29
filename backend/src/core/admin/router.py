"""
HTTP API router for the admin panel.

Four endpoints, all gated by require_admin (prefix /api/v1/admin):
GET /state, GET /tick-log, POST /tick/run, POST /state/reset.

The router owns no module tables: state views and resets are delegated to
module-provided hooks in AdminRegistry; the only table it touches directly
is the read-only tick_log audit trail. A manual tick reuses
core.tick.scheduler.run_scheduled_tick on a FRESH session — the same code
path the automatic scheduler takes — so no tick logic is duplicated here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from core.admin.security import require_admin
from core.db import get_session, get_session_context
from core.tick.scheduler import run_scheduled_tick
from modules._00_core.exceptions import CoreDomainError
from modules._00_core.models import GameClock, Player, TickLog

logger = logging.getLogger(__name__)

TICK_LOG_DEFAULT_LIMIT = 20
TICK_LOG_MAX_LIMIT = 100

router = APIRouter(prefix="/api/v1/admin")


class ConfirmRequiredError(CoreDomainError):
    """Raised when a destructive admin call lacks literal `confirm: true`."""

    def __init__(self):
        super().__init__(
            "Confirmation required: send {\"confirm\": true}",
            "CONFIRM_REQUIRED",
        )


class ModuleNotFoundError(CoreDomainError):
    """Raised when a reset targets a module_slug with no registered hook."""

    def __init__(self, module_slug: str):
        super().__init__(
            f"Module '{module_slug}' has no registered admin hooks",
            "MODULE_NOT_FOUND",
        )


class ResetFailedError(CoreDomainError):
    """Raised when a reset hook throws; maps to a 500 via the default."""

    def __init__(self, module_slug: str, cause: Exception | None = None):
        detail = f"Reset failed while running module '{module_slug}'"
        if cause is not None:
            detail += f": {type(cause).__name__}: {cause}"
        super().__init__(detail, "RESET_FAILED")


class StateResetRequest(BaseModel):
    """Body for POST /state/reset. `confirm` must be the literal true."""

    confirm: Any = None
    module_slug: str | None = None


def _iso_utc(value: datetime | None) -> str | None:
    """ISO-8601 with an explicit UTC offset; naive datetimes read as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _tick_log_dict(row: TickLog) -> dict:
    return {
        "id": row.id,
        "turn_number": row.turn_number,
        "started_at": _iso_utc(row.started_at),
        "finished_at": _iso_utc(row.finished_at),
        "status": row.status.value,
        "error_message": row.error_message,
    }


@router.get("/state")
async def admin_state(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Aggregated state view across modules.

    Each registered state-view hook is invoked in registration order. A
    failing hook degrades to {"error": "<ExceptionType>"} for its slug —
    it must never take down the whole response — and the session is rolled
    back so later hooks still run on a clean transaction.
    """
    modules: dict[str, Any] = {}
    for slug, view_hook in AdminRegistry.get_state_view_hooks().items():
        try:
            modules[slug] = await view_hook(session)
        except Exception as exc:
            logger.exception("Admin state-view hook failed for '%s'", slug)
            await session.rollback()
            modules[slug] = {"error": type(exc).__name__}
    return {"modules": modules}


@router.get("/tick-log")
async def admin_tick_log(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    limit: Annotated[
        int, Query(ge=1, le=TICK_LOG_MAX_LIMIT)
    ] = TICK_LOG_DEFAULT_LIMIT,
) -> list[dict]:
    """Newest tick_log rows first (by id). limit outside 1..100 -> 422."""
    result = await session.execute(
        select(TickLog).order_by(TickLog.id.desc()).limit(limit)
    )
    return [_tick_log_dict(row) for row in result.scalars().all()]


@router.post("/tick/run")
async def admin_tick_run(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Fire one game tick immediately, exactly like the scheduler would.

    The tick runs on a FRESH session (run_scheduled_tick owns the
    transaction boundary via session.begin()); the request session is only
    used for auth and is rolled back first so it holds no locks or snapshot
    while the tick commits from another connection.

    ok=false means the tick failed and was rolled back — the FAILED row is
    still recorded in tick_log, same as a failed automatic tick.
    """
    # Release the auth read transaction; nothing was written on it.
    await session.rollback()
    async with get_session_context() as tick_session:
        ok = await run_scheduled_tick(tick_session)
        clock_result = await tick_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = clock_result.scalar_one()
        log_result = await tick_session.execute(
            select(TickLog).order_by(TickLog.id.desc()).limit(1)
        )
        latest_log = log_result.scalar_one()
    return {
        "ok": ok,
        "current_turn": clock.current_turn,
        "next_tick_at": _iso_utc(clock.next_tick_at),
        "tick_log": _tick_log_dict(latest_log),
    }


@router.post("/state/reset")
async def admin_state_reset(
    body: StateResetRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Wipe game state back to defaults via the registered reset hooks.

    `confirm` must be the literal JSON true. Without module_slug every
    reset hook runs in REVERSE registration order (dependents first, the
    00_core base last); with module_slug only that module's hook runs.

    One transaction on the request session: all-or-nothing. If any hook
    raises, everything is rolled back and a 500 RESET_FAILED names the
    offending slug.
    """
    if body.confirm is not True:
        raise ConfirmRequiredError()

    hooks = AdminRegistry.get_reset_hooks()
    if body.module_slug is not None:
        if body.module_slug not in hooks:
            raise ModuleNotFoundError(body.module_slug)
        plan = [body.module_slug]
    else:
        plan = list(reversed(hooks))

    failed_slug = None
    try:
        for slug in plan:
            failed_slug = slug
            await hooks[slug](session)
    except Exception as exc:
        await session.rollback()
        logger.exception(
            "Admin reset failed while running hook '%s'", failed_slug
        )
        raise ResetFailedError(failed_slug, exc) from exc

    await session.commit()
    return {"reset": plan}
