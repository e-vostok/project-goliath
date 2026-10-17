"""
HTTP API router for the admin panel.

Seven endpoints, all gated by require_admin (prefix /api/v1/admin):
GET /me, GET /state, GET /tick-log, POST /tick/run, POST /state/reset,
GET /players/{vk_user_id}/delete-preview and
POST /players/{vk_user_id}/delete.

The router owns no module tables: state views and resets are delegated to
module-provided hooks in AdminRegistry; the only table it touches directly
is the read-only tick_log audit trail. A manual tick reuses
core.tick.scheduler.run_scheduled_tick on a FRESH session — the same code
path the automatic scheduler takes — so no tick logic is duplicated here.

Player deletion is the exceptional test-player cleanup tool: the preview
aggregates every module's PlayerPreviewHook into a fixed-shape "what will
disappear" response, and the delete itself goes through
PlayerService.delete_player — one transaction, all-or-nothing — after
three guards: the retyped confirm_vk_user_id must match the path id, the
target may not be the caller's own player, and may not be on the admin
allowlist at all. A WARNING audit line is logged per deletion.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from core.admin.security import is_admin_vk_user, require_admin
from core.db import get_session, get_session_context
from core.tick.orchestrator import TickOutcome
from core.tick.scheduler import run_scheduled_tick
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import CoreDomainError, PlayerNotFoundError
from modules._00_core.models import GameClock, Player, TickLog
from modules._00_core.router import GameClockNotFoundError
from modules._00_core.service import PlayerService
from modules._00_core.tick_schedule import format_game_time

logger = logging.getLogger(__name__)

TICK_LOG_DEFAULT_LIMIT = 20
TICK_LOG_MAX_LIMIT = 100

router = APIRouter(prefix="/api/v1/admin")


class ConfirmRequiredError(CoreDomainError):
    """Raised when a destructive admin call lacks literal `confirm: true`."""

    def __init__(self):
        super().__init__(
            'Confirmation required: send {"confirm": true}',
            "CONFIRM_REQUIRED",
        )


class AdminModuleNotFoundError(CoreDomainError):
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


class TickInProgressError(CoreDomainError):
    """Raised when a manual tick collides with an already-running tick."""

    def __init__(self):
        super().__init__(
            "A tick is already in progress",
            "TICK_IN_PROGRESS",
        )


class ResetDisabledError(CoreDomainError):
    """Raised when ADMIN_ALLOW_RESET gates off the world-reset endpoint."""

    def __init__(self):
        super().__init__(
            "World reset is disabled on this server",
            "RESET_DISABLED",
        )


class ConfirmationMismatchError(CoreDomainError):
    """
    The retyped ``confirm_vk_user_id`` does not match the path's
    ``vk_user_id`` — the irreversible deletion must never happen by
    accident, so the two must agree exactly.
    """

    def __init__(self):
        super().__init__(
            "confirm_vk_user_id does not match the target's vk_user_id",
            "CONFIRMATION_MISMATCH",
        )


class CannotDeleteSelfError(CoreDomainError):
    """An administrator may not delete their own player."""

    def __init__(self):
        super().__init__(
            "An administrator cannot delete their own player",
            "CANNOT_DELETE_SELF",
        )


class CannotDeleteAdminError(CoreDomainError):
    """Players whose VK id is on the admin allowlist are never deletable."""

    def __init__(self):
        super().__init__(
            "Players on the admin allowlist cannot be deleted",
            "CANNOT_DELETE_ADMIN",
        )


class PlayerDeleteFailedError(CoreDomainError):
    """Raised when the delete transaction throws; maps to a 500."""

    def __init__(self, cause: Exception):
        super().__init__(
            f"Player deletion failed and rolled back: {type(cause).__name__}: {cause}",
            "PLAYER_DELETE_FAILED",
        )


def _reset_allowed() -> bool:
    """
    Read ADMIN_ALLOW_RESET at REQUEST time (never import time), so the
    flag can be flipped for one reset without a redeploy — only a
    restart. Truthy values are 1/true/yes/on (case-insensitive,
    stripped); anything else or a missing variable fails closed.
    """
    raw = os.environ.get("ADMIN_ALLOW_RESET") or ""
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class StateResetRequest(BaseModel):
    """Body for POST /state/reset. `confirm` must be the literal true."""

    confirm: Any = None
    module_slug: str | None = None


class PlayerDeleteRequest(BaseModel):
    """
    Body for POST /players/{vk_user_id}/delete: the administrator retypes
    the target's VK id, which must equal the path's ``vk_user_id``
    exactly (compared as trimmed strings, so int and str JSON forms both
    work). Anything else is a CONFIRMATION_MISMATCH.
    """

    confirm_vk_user_id: Any = None


def _tick_log_dict(row: TickLog, tz_name: str) -> dict:
    return {
        "id": row.id,
        "turn_number": row.turn_number,
        "started_at": format_game_time(row.started_at, tz_name),
        "finished_at": format_game_time(row.finished_at, tz_name),
        "status": row.status.value,
        "error_message": row.error_message,
    }


@router.get("/me")
async def admin_me(admin: Player = Depends(require_admin)) -> dict:
    """
    Admin probe for the UI: 200 {"is_admin": true} for allowlisted users.

    Non-admins get 403 ADMIN_REQUIRED and anonymous callers 401 from
    require_admin/get_current_player — the frontend treats any non-200 as
    "not admin" and hides the admin block silently.
    """
    return {"is_admin": True}


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
    limit: Annotated[int, Query(ge=1, le=TICK_LOG_MAX_LIMIT)] = TICK_LOG_DEFAULT_LIMIT,
) -> list[dict]:
    """Newest tick_log rows first (by id). limit outside 1..100 -> 422.

    Times are 'YYYY-MM-DD HH:MM:SS' display strings in
    tick.tick_timezone; storage stays UTC.
    """
    tz_name = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    ).tick.tick_timezone
    result = await session.execute(
        select(TickLog).order_by(TickLog.id.desc()).limit(limit)
    )
    return [_tick_log_dict(row, tz_name) for row in result.scalars().all()]


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
    still recorded in tick_log, same as a failed automatic tick. A manual
    run racing another tick loses the advisory lock and answers 409
    TICK_IN_PROGRESS instead of running a second time.
    """
    # Release the auth read transaction; nothing was written on it.
    await session.rollback()
    async with get_session_context() as tick_session:
        outcome = await run_scheduled_tick(tick_session)
        if outcome is TickOutcome.SKIPPED_LOCKED:
            raise TickInProgressError()
        ok = outcome is TickOutcome.EXECUTED
        clock_result = await tick_session.execute(
            select(GameClock).where(GameClock.id == 1)
        )
        clock = clock_result.scalar_one_or_none()
        if clock is None:
            raise GameClockNotFoundError()
        log_result = await tick_session.execute(
            select(TickLog).order_by(TickLog.id.desc()).limit(1)
        )
        latest_log = log_result.scalar_one_or_none()
    tz_name = CoreConfig.from_yaml(
        CoreConfig.get_default_config_path()
    ).tick.tick_timezone
    return {
        "ok": ok,
        "current_turn": clock.current_turn,
        "next_tick_at": format_game_time(clock.next_tick_at, tz_name),
        "tick_log": (
            _tick_log_dict(latest_log, tz_name) if latest_log is not None else None
        ),
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

    The ADMIN_ALLOW_RESET gate sits after require_admin (non-admins still
    see ADMIN_REQUIRED, not RESET_DISABLED) and before any body handling.
    """
    if not _reset_allowed():
        raise ResetDisabledError()

    if body.confirm is not True:
        raise ConfirmRequiredError()

    hooks = AdminRegistry.get_reset_hooks()
    if body.module_slug is not None:
        if body.module_slug not in hooks:
            raise AdminModuleNotFoundError(body.module_slug)
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
        logger.exception("Admin reset failed while running hook '%s'", failed_slug)
        raise ResetFailedError(failed_slug, exc) from exc

    await session.commit()
    return {"reset": plan}


async def _load_player_by_vk_id(session: AsyncSession, vk_user_id: int) -> Player:
    """The target's player row or 404 PLAYER_NOT_FOUND."""
    result = await session.execute(
        select(Player).where(Player.vk_user_id == vk_user_id)
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise PlayerNotFoundError(f"vk_user_id={vk_user_id}")
    return player


async def _player_delete_preview(session: AsyncSession, player: Player) -> dict:
    """
    The fixed-shape delete-preview response for one player.

    Starts from zeroed defaults, then merges every registered module's
    PlayerPreviewHook fragment — the response contract below is the API,
    the fragments are how each module reports its own share. A failing
    fragment propagates: a wrong preview must never authorize a real
    deletion.
    """
    preview: dict[str, Any] = {
        "vk_user_id": player.vk_user_id,
        "nation_name": None,
        "provinces_released": 0,
        "orders_author": 0,
        "orders_judge_undecided": 0,
        "orders_judge_decided": 0,
        "outbox_rows": 0,
        "consent_rows": 0,
        "vk_profile_rows": 0,
    }
    for preview_hook in AdminRegistry.get_player_preview_hooks().values():
        fragment = await preview_hook(session, player.id)
        preview.update(fragment)
    return preview


@router.get("/players/{vk_user_id}/delete-preview")
async def admin_player_delete_preview(
    vk_user_id: int,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    What deleting this player would remove — read-only, never commits.

    The counts come from the same module hooks' preview halves as the
    real deletion, so a positive preview is an honest statement of the
    destructive operation. 404 PLAYER_NOT_FOUND for unknown targets.
    """
    player = await _load_player_by_vk_id(session, vk_user_id)
    return await _player_delete_preview(session, player)


@router.post("/players/{vk_user_id}/delete")
async def admin_player_delete(
    vk_user_id: int,
    body: PlayerDeleteRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Delete a player and everything tied to them — irreversible.

    Guards, in order: the target must exist (404); it may not be the
    caller's own player (409 CANNOT_DELETE_SELF) nor any allowlisted
    admin (409 CANNOT_DELETE_ADMIN); the retyped confirm_vk_user_id must
    match the path id (422 CONFIRMATION_MISMATCH).

    The deletion itself is PlayerService.delete_player on the request
    session — one transaction, all-or-nothing: nation deletion
    (provinces freed, journal written), every module's player-delete
    hook, then the players row. Any failure rolls everything back and
    answers 500 PLAYER_DELETE_FAILED. One WARNING audit line logs the
    admin's vk id, the target's vk id and the deletion counts.
    """
    player = await _load_player_by_vk_id(session, vk_user_id)

    if player.vk_user_id == admin.vk_user_id:
        raise CannotDeleteSelfError()
    if is_admin_vk_user(player.vk_user_id):
        raise CannotDeleteAdminError()
    if body.confirm_vk_user_id is None or str(body.confirm_vk_user_id).strip() != str(
        vk_user_id
    ):
        raise ConfirmationMismatchError()

    preview = await _player_delete_preview(session, player)
    try:
        await PlayerService.delete_player(session, player.id)
    except Exception as exc:
        await session.rollback()
        logger.exception("Admin player delete failed for vk_user_id %s", vk_user_id)
        raise PlayerDeleteFailedError(exc) from exc

    await session.commit()
    logger.warning(
        "admin_player_delete admin_vk_user_id=%s target_vk_user_id=%s counts=%s",
        admin.vk_user_id,
        vk_user_id,
        preview,
    )
    return preview
