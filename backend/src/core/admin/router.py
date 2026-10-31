"""
HTTP API router for the admin panel.

Twenty-eight endpoints (prefix /api/v1/admin): GET /me, GET /state,
GET /players, GET /provinces,
GET /provinces/{province_id}/transfer-preview,
POST /provinces/{province_id}/transfer, GET /nations, POST /nations,
GET /nations/{nation_id}, PATCH /nations/{nation_id},
POST /nations/color-check, GET /nations/{nation_id}/delete-preview,
POST /nations/{nation_id}/delete,
GET /nations/{nation_id}/images/{kind}/delete-preview,
POST /nations/{nation_id}/images/{kind}/delete, GET /overview, GET /tick-log,
POST /tick/run, POST /state/reset,
GET /players/{vk_user_id}/delete-preview,
POST /players/{vk_user_id}/delete, POST /panel-link, POST /session,
GET /audit-log, GET /audit-log/filters, GET /admins, POST /admins and
POST /admins/{vk_user_id}/revoke.

All but POST /session are gated by require_admin. The panel-link /
session pair implements the one-time-link entry of 0.11.0 unit 4: an
administrator inside the Mini App gets a link token, a bare browser tab
exchanges it for a short Bearer JWT — the same kind every other admin
endpoint accepts, with rights re-read from the database on each request.
Both responses carry Cache-Control: no-store; a successful exchange
writes one panel.login audit row, a failed one a WARNING log line —
the raw token is never stored nor logged.

The router owns no module tables: state views and resets are delegated to
module-provided hooks in AdminRegistry; the only tables it touches directly
are the read-only tick_log audit trail and the admin_audit_log journal —
every mutating endpoint (tick.run, world.reset, player.delete) writes one
journal row inside its request transaction via AdminAuditService. A manual
tick reuses core.tick.scheduler.run_scheduled_tick on a FRESH session — the
same code path the automatic scheduler takes — so no tick logic is
duplicated here.

Player deletion is the exceptional test-player cleanup tool: the preview
aggregates every module's PlayerPreviewHook into a fixed-shape "what will
disappear" response, and the delete itself goes through
PlayerService.delete_player — one transaction, all-or-nothing — after
three guards: the retyped confirm_vk_user_id must match the path id, the
target may not be the caller's own player, and may not be an admin at all
(env allowlist or admin_grants row). A WARNING audit line is logged per
deletion, alongside the journal row.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin import panel_access
from core.admin.registry import AdminRegistry
from core.admin.security import _admin_vk_user_ids, is_admin_user, require_admin
from core.db import get_session, get_session_context
from core.security.jwt import issue_token
from core.tick.orchestrator import TickOutcome
from core.tick.scheduler import run_scheduled_tick
from modules._00_core import images
from modules._00_core.admin_service import (
    AdminAuditService,
    AdminGrantService,
)
from modules._00_core.calendar import compute_game_date, format_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    CoreDomainError,
    ImageNotFoundError,
    NationNotFoundError,
    PlayerNotFoundError,
    ProvinceNameUnknownError,
    ProvinceNotFoundError,
    ProvinceNotLandError,
)
from modules._00_core.models import (
    AdminGrant,
    GameClock,
    Nation,
    Player,
    Province,
    TickLog,
)
from modules._00_core.router import GameClockNotFoundError
from modules._00_core.schemas import _COLOR_HEX_PATTERN, _validate_nation_name
from modules._00_core.service import (
    NationService,
    PlayerService,
    ProvinceService,
)
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
    """Players with admin rights (env allowlist or a grant) are never deletable."""

    def __init__(self):
        super().__init__(
            "Players with admin rights cannot be deleted",
            "CANNOT_DELETE_ADMIN",
        )


class PlayerDeleteFailedError(CoreDomainError):
    """Raised when the delete transaction throws; maps to a 500."""

    def __init__(self, cause: Exception):
        super().__init__(
            f"Player deletion failed and rolled back: {type(cause).__name__}: {cause}",
            "PLAYER_DELETE_FAILED",
        )


class NationDeleteFailedError(CoreDomainError):
    """Raised when the nation delete transaction throws; maps to a 500."""

    def __init__(self, cause: Exception):
        super().__init__(
            f"Nation deletion failed and rolled back: {type(cause).__name__}: {cause}",
            "NATION_DELETE_FAILED",
        )


class CannotRevokeSelfError(CoreDomainError):
    """An administrator may not revoke their own admin rights."""

    def __init__(self):
        super().__init__(
            "An administrator cannot revoke their own rights",
            "CANNOT_REVOKE_SELF",
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


class PanelSessionRequest(BaseModel):
    """Body for POST /session: the one-time link token from the tab."""

    token: str


class PlayerDeleteRequest(BaseModel):
    """
    Body for POST /players/{vk_user_id}/delete: the administrator retypes
    the target's VK id, which must equal the path's ``vk_user_id``
    exactly (compared as trimmed strings, so int and str JSON forms both
    work). Anything else is a CONFIRMATION_MISMATCH.
    """

    confirm_vk_user_id: Any = None


class AdminGrantRequest(BaseModel):
    """Body for POST /admins: the VK id of the player to grant."""

    vk_user_id: int


class AdminNationCreateRequest(BaseModel):
    """
    Body for POST /nations (0.11.0 unit 8a): the simplified admin
    creation — no questionnaire, but the same format checks as the
    player's own form: the name length is validated here on the
    stripped value, ``color_hex`` carries the fixed ``#RRGGBB``
    pattern, everything else is NationService's own domain check in
    its own order. The first of ``province_ids`` is the capital unless
    ``capital_province_id`` picks another member.
    """

    owner_vk_user_id: int
    name: str
    short_name: str
    color_hex: str = Field(pattern=_COLOR_HEX_PATTERN)
    leader_name: str
    leader_title: str
    gender: str
    succession_type: str
    history_url: str
    motto: str | None = None
    province_ids: list[int]
    capital_province_id: int | None = None

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str) -> str:
        return _validate_nation_name(value)

    @field_validator("province_ids")
    @classmethod
    def check_province_ids_unique(cls, value: list[int]) -> list[int]:
        """
        A repeated id would pass the count check while claiming fewer
        provinces than the list suggests (0.11.0 unit 8b fix to 8a).
        """
        if len(set(value)) != len(value):
            raise ValueError("province_ids must not contain duplicates")
        return value


# The twelve descriptive fields PATCH /admin/nations/{id} accepts —
# the player's edit-window set (INV-8), minus flag, portrait, anthem
# and anything province-related. Order is the audit summary's.
NATION_EDITABLE_FIELDS: tuple[str, ...] = (
    "name",
    "short_name",
    "color_hex",
    "motto",
    "description",
    "leader_name",
    "leader_title",
    "gender",
    "succession_type",
    "leader_bio",
    "history_url",
    "capital_name",
)

# The Russian field names for the nation.update journal summary —
# keyed by the request's field codes.
NATION_FIELD_LABELS: dict[str, str] = {
    "name": "полное название",
    "short_name": "краткое название",
    "color_hex": "цвет",
    "motto": "девиз",
    "description": "описание",
    "leader_name": "имя лидера",
    "leader_title": "должность лидера",
    "gender": "пол лидера",
    "succession_type": "преемственность",
    "leader_bio": "биография лидера",
    "history_url": "ссылка на историю",
    "capital_name": "столица",
}


class AdminNationUpdateRequest(BaseModel):
    """
    Body for PATCH /nations/{nation_id} (0.11.0 unit 8b): only the
    twelve editable fields, all optional — absent/None means "do not
    change", "" on an optional field clears it to NULL, "" on a
    mandatory field is the service's own *_INVALID error (INV-8).

    ``extra="forbid"``: an anthem, picture or province field is
    a 422, not a silent ignore.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    short_name: str | None = None
    color_hex: str | None = Field(default=None, pattern=_COLOR_HEX_PATTERN)
    motto: str | None = None
    description: str | None = None
    leader_name: str | None = None
    leader_title: str | None = None
    gender: str | None = None
    succession_type: str | None = None
    leader_bio: str | None = None
    history_url: str | None = None
    capital_name: str | None = None

    @field_validator("name")
    @classmethod
    def check_name_length(cls, value: str | None) -> str | None:
        return _validate_nation_name(value)


class AdminNationColorCheckRequest(BaseModel):
    """Body for POST /nations/color-check: the colour plus, on the
    edit page, the nation whose own colour is excluded."""

    color_hex: str = Field(pattern=_COLOR_HEX_PATTERN)
    nation_id: str | None = None


class NationDeleteRequest(BaseModel):
    """
    Body for POST /nations/{nation_id}/delete (0.11.0 unit 8c): the
    administrator retypes the nation's short name — it must equal it
    exactly after trimming (same rule as the player deletion's
    retyped VK id), anything else is a CONFIRMATION_MISMATCH.
    """

    confirm_short_name: Any = None


class ProvinceTransferRequest(BaseModel):
    """
    Body for POST /provinces/{province_id}/transfer (0.11.0 unit 9a):
    ``to_nation_id`` is the target nation — explicit null means
    "free the province"; ``confirm_seize`` is the separate
    confirmation for taking a province owned by another nation;
    ``new_capital_province_id`` picks the donor's replacement capital
    when the moved province was its capital (its display name comes
    from the province-info hooks — the service never sees raw names).
    """

    model_config = ConfigDict(extra="forbid")

    to_nation_id: str | None = None
    confirm_seize: bool = False
    new_capital_province_id: int | None = None


def _tick_log_dict(row: TickLog, config: CoreConfig) -> dict:
    game_date = format_game_date(compute_game_date(row.turn_number, config), config)
    return {
        "id": row.id,
        "turn_number": row.turn_number,
        # «1 · январь 2040» — the same derived game date the game clock
        # shows, in lowercase like the approved panel mockup.
        "turn_label": f"{row.turn_number} · {game_date.lower()}",
        "started_at": format_game_time(row.started_at, config.tick.tick_timezone),
        "finished_at": format_game_time(row.finished_at, config.tick.tick_timezone),
        "status": row.status.value,
        "error_message": row.error_message,
    }


@router.get("/me")
async def admin_me(admin: Player = Depends(require_admin)) -> dict:
    """
    Admin probe for the UI: 200 {"is_admin": true, "reset_allowed": bool}.

    `reset_allowed` is the request-time ADMIN_ALLOW_RESET read — the
    panel uses it to keep the world-reset button disabled on servers
    where the flag is off. Non-admins get 403 ADMIN_REQUIRED and
    anonymous callers 401 from require_admin/get_current_player — the
    frontend treats any non-200 as "not admin" and hides the admin
    block silently.
    """
    return {"is_admin": True, "reset_allowed": _reset_allowed()}


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


async def _collect_player_info(
    session: AsyncSession, player_ids: list[str]
) -> dict[str, dict]:
    """
    Merge every player-info hook's columns for one page of players.

    A failing hook is logged, its session work rolled back and its
    columns skipped — one broken module must never take the whole
    «Игроки» table down, the same rule the state views follow.
    """
    info: dict[str, dict] = {}
    for slug, (info_fn, _) in AdminRegistry.get_player_info_hooks().items():
        try:
            columns = await info_fn(session, player_ids)
        except Exception:
            logger.exception("Admin player-info hook failed for '%s'", slug)
            await session.rollback()
            continue
        for player_id, fields in (columns or {}).items():
            info.setdefault(player_id, {}).update(fields)
    return info


async def _collect_province_info(
    session: AsyncSession, province_ids: list[int]
) -> dict[int, dict]:
    """
    Merge every province-info hook's columns for one page of provinces
    (0.11.0 unit 8a).

    A failing hook is logged, its session work rolled back and its
    columns skipped — one broken module must never take the province
    pickers down, the same rule the player columns follow.
    """
    info: dict[int, dict] = {}
    for slug, (info_fn, _) in AdminRegistry.get_province_info_hooks().items():
        try:
            columns = await info_fn(session, province_ids)
        except Exception:
            logger.exception("Admin province-info hook failed for '%s'", slug)
            await session.rollback()
            continue
        for province_id, fields in (columns or {}).items():
            info.setdefault(province_id, {}).update(fields)
    return info


@router.get("/players")
async def list_players(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """
    The panel's «Игроки» list (0.11.0 unit 6b): one page of players
    ordered by registration then id — ``{"items", "total"}``. Each item
    carries ``vk_user_id``, ``display_name`` assembled through the
    player-info hooks (null when no module knows one), ``registry_number``
    the player's permanent Registry number from the same hooks (null
    until the registry has issued one), ``nation_short_name`` (null for
    a nationless player), ``created_at`` formatted in the tick timezone
    like every admin answer, and ``is_admin`` — env allowlist or grant —
    computed once for the page, not per row.

    ``search`` is an OR over an exact VK id, a case-insensitive
    substring of the nation short/full name and every hook's search.
    The match runs in Python — the same way the registry's cell search
    does — because SQLite's ``lower()`` only folds ASCII and the
    players table is small enough for an admin tool; a failing search
    hook is logged, rolled back and skipped.
    """
    text = (search or "").strip()
    hook_player_ids: set[str] = set()
    if text:
        for slug, (_, search_fn) in AdminRegistry.get_player_info_hooks().items():
            if search_fn is None:
                continue
            try:
                found = await search_fn(session, text)
            except Exception:
                logger.exception("Admin player-search hook failed for '%s'", slug)
                await session.rollback()
                continue
            hook_player_ids.update(found or set())

    rows_all = (
        await session.execute(
            select(
                Player.id,
                Player.vk_user_id,
                Player.created_at,
                Nation.short_name,
                Nation.name,
            )
            .outerjoin(Nation, Nation.owner_player_id == Player.id)
            .order_by(Player.created_at, Player.id)
        )
    ).all()

    if text:
        lowered = text.lower()
        exact_vk = int(text) if text.isdigit() else None
        rows_all = [
            row
            for row in rows_all
            if (exact_vk is not None and row.vk_user_id == exact_vk)
            or row.id in hook_player_ids
            or (row.short_name and lowered in row.short_name.lower())
            or (row.name and lowered in row.name.lower())
        ]
    total = len(rows_all)
    rows = rows_all[offset : offset + limit]

    info = await _collect_player_info(session, [row.id for row in rows])

    # The admin set is the env allowlist plus the granted players' vk
    # ids — the same union the overview tile and AdminGrantService use.
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    granted_vk_ids = (
        await session.execute(
            select(Player.vk_user_id).join(
                AdminGrant, AdminGrant.player_id == Player.id
            )
        )
    ).all()
    admin_vk_ids = {vk for (vk,) in granted_vk_ids} | _admin_vk_user_ids()

    return {
        "items": [
            {
                "vk_user_id": row.vk_user_id,
                "display_name": info.get(row.id, {}).get("display_name"),
                "registry_number": info.get(row.id, {}).get("registry_number"),
                "nation_short_name": row.short_name,
                "created_at": format_game_time(
                    row.created_at, config.tick.tick_timezone
                ),
                "is_admin": row.vk_user_id in admin_vk_ids,
            }
            for row in rows
        ],
        "total": total,
    }


@router.get("/provinces")
async def list_provinces(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    search: str | None = None,
    free_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """
    The panel's province picker list (0.11.0 unit 8a): LAND provinces
    only, ``{"items", "total"}``, ordered by the province's display name
    (case-folded in Python, same as the players list's Cyrillic sort)
    then id. Each item carries ``id``, the ``name`` assembled through
    the province-info hooks (null when no module knows one),
    ``nation_id`` and the owner's ``nation_short_name``.

    ``free_only`` keeps only unowned rows; ``search`` filters by the
    hooks' own name search — a failing search hook is logged, rolled
    back and skipped. The endpoint serves both the nation-creation
    picker and unit 9's province tools.
    """
    text = (search or "").strip()
    hook_province_ids: set[int] = set()
    if text:
        for slug, (_, search_fn) in AdminRegistry.get_province_info_hooks().items():
            if search_fn is None:
                continue
            try:
                found = await search_fn(session, text)
            except Exception:
                logger.exception("Admin province-search hook failed for '%s'", slug)
                await session.rollback()
                continue
            hook_province_ids.update(found or set())

    rows = (
        await session.execute(
            select(Province.id, Province.nation_id, Nation.short_name)
            .outerjoin(Nation, Province.nation_id == Nation.id)
            .where(Province.kind == "LAND")
        )
    ).all()
    if free_only:
        rows = [row for row in rows if row.nation_id is None]
    if text:
        rows = [row for row in rows if row.id in hook_province_ids]

    info = await _collect_province_info(session, [row.id for row in rows])
    rows = sorted(
        rows,
        key=lambda row: (
            (info.get(row.id, {}).get("name") or "").casefold(),
            row.id,
        ),
    )
    total = len(rows)
    page = rows[offset : offset + limit]
    # One image_refs for the whole page (0.12.0 unit 9): the flag of
    # the OWNING nation — a free province gets null.
    refs = await NationService.image_refs(
        session, [row.nation_id for row in page if row.nation_id is not None]
    )
    return {
        "items": [
            {
                "id": row.id,
                "name": info.get(row.id, {}).get("name"),
                "nation_id": row.nation_id,
                "nation_short_name": row.short_name,
                "flag_thumb_url": (
                    images.image_url(refs[row.nation_id].flag_sha256, "thumb")
                    if row.nation_id is not None
                    else None
                ),
            }
            for row in page
        ],
        "total": total,
    }


@router.get("/provinces/{province_id}/transfer-preview")
async def admin_province_transfer_preview(
    province_id: int,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    to_nation_id: str | None = None,
) -> dict:
    """
    What transferring this province would do — read-only, never
    commits (0.11.0 unit 9a). No ``to_nation_id`` previews a release.

    The fixed shape tells the panel everything the action endpoint
    would check, without performing it: the province (display name
    through the province-info hooks), the donor nation (or null for a
    free province), the receiver (or null), whether the call would
    seize from another nation, whether a new capital must be chosen
    and the donor's remaining provinces as ``capital_candidates``
    (ordered by name, same rule as the nation delete-preview), the
    province counts after the operation, and a ``blocker`` naming the
    refusal the action would hit (``LAST_PROVINCE``,
    ``ALREADY_OWNER``) — null when it would pass.

    Unknown province -> 404 PROVINCE_NOT_FOUND; a sea zone -> 422
    PROVINCE_NOT_LAND; unknown target nation -> 404 NATION_NOT_FOUND.
    """
    province = await session.get(Province, province_id)
    if province is None:
        raise ProvinceNotFoundError(province_id)
    if province.kind != "LAND":
        raise ProvinceNotLandError(province_id)

    to_nation = None
    if to_nation_id is not None:
        to_nation = await session.get(Nation, to_nation_id)
        if to_nation is None:
            raise NationNotFoundError(to_nation_id)

    donor = None
    donor_province_ids: list[int] = []
    if province.nation_id is not None:
        donor = await session.get(Nation, province.nation_id)
        donor_province_ids = list(
            (
                await session.execute(
                    select(Province.id).where(Province.nation_id == donor.id)
                )
            ).scalars()
        )

    receiver_count = 0
    if to_nation is not None:
        receiver_count = (
            await session.execute(
                select(func.count())
                .select_from(Province)
                .where(Province.nation_id == to_nation.id)
            )
        ).scalar_one()

    remaining_ids = [pid for pid in donor_province_ids if pid != province_id]
    info = await _collect_province_info(session, [province_id, *remaining_ids])
    candidates = sorted(
        ({"id": pid, "name": info.get(pid, {}).get("name")} for pid in remaining_ids),
        key=lambda item: ((item["name"] or "").casefold(), item["id"]),
    )

    blocker = None
    if province.nation_id == to_nation_id:
        # Already the target's — or already free on a release.
        blocker = "ALREADY_OWNER"
    elif donor is not None and len(donor_province_ids) == 1:
        blocker = "LAST_PROVINCE"

    return {
        "province": {
            "id": province.id,
            "name": info.get(province_id, {}).get("name"),
        },
        "from_nation": (
            None
            if donor is None
            else {
                "id": donor.id,
                "short_name": donor.short_name,
                "provinces_count": len(donor_province_ids),
                "capital_province_id": donor.capital_province_id,
                "capital_name": donor.capital_name,
            }
        ),
        "to_nation": (
            None
            if to_nation is None
            else {
                "id": to_nation.id,
                "short_name": to_nation.short_name,
                "provinces_count": receiver_count,
            }
        ),
        "seizes": donor is not None and to_nation is not None,
        "capital_choice_needed": (
            donor is not None and donor.capital_province_id == province_id
        ),
        "capital_candidates": candidates,
        "donor_after": (None if donor is None else len(donor_province_ids) - 1),
        "receiver_after": (None if to_nation is None else receiver_count + 1),
        "blocker": blocker,
    }


@router.post("/provinces/{province_id}/transfer")
async def admin_province_transfer(
    province_id: int,
    body: ProvinceTransferRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Move a province to a nation — or free it (0.11.0 unit 9a).

    Calls the unchanged ``ProvinceService.transfer``: every domain
    refusal keeps its HTTP code, rolls the transaction back and writes
    no journal row. When ``new_capital_province_id`` is set, the new
    capital's name is the chosen province's display name through the
    province-info hooks — 422 PROVINCE_NAME_UNKNOWN when no hook knows
    one.

    On success one ``province.transfer`` journal row lands in the same
    transaction, before the commit: the summary is one Russian
    sentence, ``details`` carries ids and the ``seized`` flag only.
    The map's ownership journal is written by its own listener — not
    here. The answer is the service result: ``province_id``,
    ``previous_nation_id``, ``new_nation_id``,
    ``new_capital_province_id``.
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

    new_capital_name = None
    if body.new_capital_province_id is not None:
        capital_info = await _collect_province_info(
            session, [body.new_capital_province_id]
        )
        new_capital_name = capital_info.get(body.new_capital_province_id, {}).get(
            "name"
        )
        if new_capital_name is None:
            raise ProvinceNameUnknownError(body.new_capital_province_id)

    result = await ProvinceService.transfer(
        session,
        province_id,
        body.to_nation_id,
        new_capital_province_id=body.new_capital_province_id,
        new_capital_name=new_capital_name,
        confirm_seize=body.confirm_seize,
        config=config,
    )

    # Names for the audit sentence: the province's display name through
    # the hooks (falling back to the bare id — the journal must write
    # regardless), the nations' own short names for the state labels.
    info = await _collect_province_info(session, [province_id])
    province_subject = info.get(province_id, {}).get("name") or str(province_id)
    short_names: dict[str, str] = {}
    for nation_id in (result.previous_nation_id, result.new_nation_id):
        if nation_id is not None:
            nation = await session.get(Nation, nation_id)
            short_names[nation_id] = nation.short_name

    if result.previous_nation_id is None:
        summary = (
            f"Свободная провинция «{province_subject}» передана "
            f"государству «{short_names[result.new_nation_id]}»."
        )
    elif result.new_nation_id is None:
        summary = (
            f"Провинция «{province_subject}» выведена из-под "
            f"государства «{short_names[result.previous_nation_id]}»."
        )
    else:
        summary = (
            f"Провинция «{province_subject}» передана: "
            f"«{short_names[result.previous_nation_id]}» → "
            f"«{short_names[result.new_nation_id]}»."
        )
    if result.new_capital_province_id is not None:
        summary += f" Новая столица — «{new_capital_name}»."

    seized = result.previous_nation_id is not None and result.new_nation_id is not None
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="province.transfer",
        target_type="province",
        target_id=str(province_id),
        summary=summary,
        details={
            "province_id": province_id,
            "previous_nation_id": result.previous_nation_id,
            "new_nation_id": result.new_nation_id,
            "new_capital_province_id": result.new_capital_province_id,
            "seized": seized,
        },
    )
    await session.commit()
    return {
        "province_id": result.province_id,
        "previous_nation_id": result.previous_nation_id,
        "new_nation_id": result.new_nation_id,
        "new_capital_province_id": result.new_capital_province_id,
    }


@router.get("/nations")
async def list_nations(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    search: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """
    The panel's «Государства» list (0.11.0 unit 8a): one page of nations
    ordered by creation then id — ``{"items", "total"}``. Each item
    carries ``id``, ``short_name``, ``name``,
    ``owner_vk_user_id``, the ``owner_name`` the player-info hooks know
    (null when none does), ``provinces_count`` and ``capital_name``.

    ``search`` is a case-insensitive substring over the short and full
    name — case-folded in Python like the players list, because
    SQLite's ``lower()`` only folds ASCII.
    """
    text = (search or "").strip()
    rows_all = (
        await session.execute(
            select(
                Nation.id,
                Nation.short_name,
                Nation.name,
                Nation.capital_name,
                Player.vk_user_id,
            )
            .join(Player, Nation.owner_player_id == Player.id)
            .order_by(Nation.created_at, Nation.id)
        )
    ).all()
    if text:
        lowered = text.casefold()
        rows_all = [
            row
            for row in rows_all
            if lowered in row.name.casefold() or lowered in row.short_name.casefold()
        ]
    total = len(rows_all)
    rows = rows_all[offset : offset + limit]

    counts: dict[str, int] = {}
    if rows:
        pairs = (
            await session.execute(
                select(Province.nation_id, func.count())
                .where(Province.nation_id.in_([row.id for row in rows]))
                .group_by(Province.nation_id)
            )
        ).all()
        counts = {nation_id: count for nation_id, count in pairs}

    names = await _display_names_by_vk(session, {row.vk_user_id for row in rows})
    # One image_refs for the whole page (0.12.0 unit 9) — never per row.
    refs = await NationService.image_refs(session, [row.id for row in rows])
    return {
        "items": [
            {
                "id": row.id,
                "short_name": row.short_name,
                "name": row.name,
                "owner_vk_user_id": row.vk_user_id,
                "owner_name": names.get(row.vk_user_id),
                "provinces_count": counts.get(row.id, 0),
                "capital_name": row.capital_name,
                "flag_thumb_url": images.image_url(refs[row.id].flag_sha256, "thumb"),
            }
            for row in rows
        ],
        "total": total,
    }


@router.post("/nations")
async def create_nation(
    body: AdminNationCreateRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Create a nation for a chosen player (0.11.0 unit 8a): the simplified
    admin path — no questionnaire, no review, but the SAME
    NationService.create the player's own registration calls, so every
    check applies in its own order (field format, uniqueness, colour,
    province freedom and count, capital membership, satellite checks).

    Unknown owner -> 404 PLAYER_NOT_FOUND. The nation is created
    without pictures (the flag and the portrait arrive with the
    upload, unit 6); ``capital_name`` is the
    capital province's display name resolved through the province-info
    hooks. On success one ``nation.create`` journal row is written in
    the same transaction, before the commit — a refusal rolls
    everything back and writes nothing.
    """
    player = await _load_player_by_vk_id(session, body.owner_vk_user_id)
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

    # The capital: the explicit pick, else the first province sent —
    # the same default NationService.create applies internally.
    capital_id = body.capital_province_id
    if capital_id is None and body.province_ids:
        capital_id = body.province_ids[0]
    capital_name = None
    if capital_id is not None:
        capital_info = await _collect_province_info(session, [capital_id])
        capital_name = capital_info.get(capital_id, {}).get("name")
    if capital_name is None:
        # Only a refusal path reaches here (no provinces / unknown
        # capital id): the placeholder passes the field's format check
        # so the service's own later check fires in its own order — it
        # is never stored, every failure rolls back.
        capital_name = (
            f"Провинция {capital_id if capital_id is not None else ''}".strip()
        )

    nation = await NationService.create(
        session,
        owner_player_id=player.id,
        name=body.name,
        color_hex=body.color_hex,
        province_ids=body.province_ids,
        config=config,
        leader_name=body.leader_name,
        leader_title=body.leader_title,
        history_url=body.history_url,
        short_name=body.short_name,
        gender=body.gender,
        succession_type=body.succession_type,
        capital_name=capital_name,
        capital_province_id=body.capital_province_id,
        motto=body.motto,
    )

    names = await _display_names_by_vk(session, {player.vk_user_id})
    owner_subject = names.get(player.vk_user_id, str(player.vk_user_id))
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="nation.create",
        target_type="nation",
        target_id=nation.id,
        summary=(
            f"Создано государство «{nation.short_name}» для игрока {owner_subject}."
        ),
        details={
            "nation_id": nation.id,
            "owner_player_id": player.id,
            "owner_vk_user_id": player.vk_user_id,
            "capital_province_id": nation.capital_province_id,
            "province_ids": body.province_ids,
        },
    )
    refs = await NationService.image_refs(session, [nation.id])
    await session.commit()
    return {
        "id": nation.id,
        "short_name": nation.short_name,
        "name": nation.name,
        "owner_vk_user_id": player.vk_user_id,
        "owner_name": names.get(player.vk_user_id),
        "provinces_count": len(body.province_ids),
        "capital_name": nation.capital_name,
        "flag_thumb_url": images.image_url(refs[nation.id].flag_sha256, "thumb"),
    }


@router.post("/nations/color-check")
async def admin_nation_color_check(
    body: AdminNationColorCheckRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    The panel's own colour decision (0.11.0 unit 8b): the same
    ``NationService.color_status`` the player's form consults, with
    ``nation_id`` excluding the edited nation itself. Read-only.
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    return {
        "status": await NationService.color_status(
            session,
            body.color_hex,
            config,
            exclude_nation_id=body.nation_id,
        )
    }


# The uploaded-picture kinds of nation_images (INV-15) — a ``kind``
# outside them is a bare 404, the same style the player's upload
# endpoint uses.
_IMAGE_KINDS = ("flag", "portrait")

# The «Что будет» sentences of the image-delete confirmation window
# (mockup 18b) — the first sentence is kind-specific, the journal
# sentence is shared.
_IMAGE_DELETE_CONSEQUENCES = {
    "flag": (
        "картинка удаляется с сервера насовсем; в приказах, где "
        "показан этот флаг, тоже появится заглушка"
    ),
    "portrait": (
        "картинка удаляется с сервера насовсем; везде, где показан "
        "этот портрет, тоже появится заглушка"
    ),
}
_IMAGE_DELETE_AUDIT_LINE = "в журнал попадёт запись «Удаление картинки государства»"


def _iso_utc(moment: datetime) -> str:
    """ISO 8601 with an explicit offset — storage is UTC; SQLite reads
    the column back naive, so the tz is attached, never converted."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


async def _image_uploaded_by(
    session: AsyncSession, player_id: str | None
) -> dict | None:
    """{vk_user_id, name} of a picture's uploader — null when the
    uploading player no longer exists; the name comes from the
    display-name hooks and may itself be null."""
    if player_id is None:
        return None
    player = await session.get(Player, player_id)
    if player is None:
        return None
    names = await _display_names_by_vk(session, {player.vk_user_id})
    return {
        "vk_user_id": player.vk_user_id,
        "name": names.get(player.vk_user_id),
    }


async def _nation_edit_dto(session: AsyncSession, nation: Nation) -> dict:
    """The GET/PATCH nation shape: the twelve editable fields plus
    the read-only owner, capital province, province count and the
    ``images`` block of the nation's uploaded pictures (0.12.0 unit
    8) — one entry per kind or null for a kind never uploaded."""
    owner = (
        await session.execute(select(Player).where(Player.id == nation.owner_player_id))
    ).scalar_one()
    provinces_count = (
        await session.execute(
            select(func.count())
            .select_from(Province)
            .where(Province.nation_id == nation.id)
        )
    ).scalar_one()
    image_infos = await NationService.image_info(session, nation.id)
    names = await _display_names_by_vk(session, {owner.vk_user_id})
    # The pipeline's target size of each kind (0.12.0 unit 9) — read
    # through the config model, never hard-coded.
    image_config = CoreConfig.from_yaml(CoreConfig.get_default_config_path()).images
    image_dims = {
        "flag": (image_config.flag_width, image_config.flag_height),
        "portrait": (
            image_config.portrait_width,
            image_config.portrait_height,
        ),
    }
    return {
        "id": nation.id,
        "owner_vk_user_id": owner.vk_user_id,
        "owner_name": names.get(owner.vk_user_id),
        "capital_province_id": nation.capital_province_id,
        "provinces_count": provinces_count,
        **{field: getattr(nation, field) for field in NATION_EDITABLE_FIELDS},
        "images": {
            kind: (
                None
                if image_infos[kind] is None
                else {
                    "url": image_infos[kind].url,
                    "thumb_url": image_infos[kind].thumb_url,
                    "uploaded_at": _iso_utc(image_infos[kind].uploaded_at),
                    "uploaded_by": await _image_uploaded_by(
                        session, image_infos[kind].uploaded_by_player_id
                    ),
                    "size_bytes": image_infos[kind].size_bytes,
                    "width": image_dims[kind][0],
                    "height": image_dims[kind][1],
                }
            )
            for kind in _IMAGE_KINDS
        },
    }


@router.get("/nations/{nation_id}")
async def get_nation(
    nation_id: str,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    The edit page's data (0.11.0 unit 8b): the twelve editable fields
    plus ``id``, ``owner_vk_user_id``, ``owner_name`` (player-info
    hooks), ``capital_province_id`` and ``provinces_count``. Unknown
    id -> 404 NATION_NOT_FOUND.
    """
    nation = (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(nation_id)
    return await _nation_edit_dto(session, nation)


@router.patch("/nations/{nation_id}")
async def update_nation(
    nation_id: str,
    body: AdminNationUpdateRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Edit a nation's main data (0.11.0 unit 8b): the unchanged
    ``NationService.update`` with its PATCH semantics — only the sent
    fields are checked and written; flag, portrait, provinces and the
    capital province are never touched (a stray key is a 422 from the
    request model). An empty change set -> 400 NOTHING_TO_CHANGE.

    One ``nation.update`` journal row lands in the same transaction
    before the commit — summary names the changed fields in Russian,
    ``details`` carries ids and the field CODES only, never the texts.
    A refusal rolls everything back and writes nothing.
    """
    changes = {
        field: value
        for field, value in body.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not changes:
        # main.py's map is version-only for this unit — the refusal is
        # answered in the handler's own {detail, code, details} shape.
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Nothing to change",
                "code": "NOTHING_TO_CHANGE",
            },
        )
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    nation = await NationService.update(
        session,
        nation_id=nation_id,
        config=config,
        **changes,
    )

    changed_labels = [
        NATION_FIELD_LABELS[field]
        for field in NATION_EDITABLE_FIELDS
        if field in changes
    ]
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="nation.update",
        target_type="nation",
        target_id=nation.id,
        summary=(
            f"Изменены данные государства «{nation.short_name}»: "
            f"{', '.join(changed_labels)}."
        ),
        details={
            "nation_id": nation.id,
            "owner_player_id": nation.owner_player_id,
            "fields": [field for field in NATION_EDITABLE_FIELDS if field in changes],
        },
    )
    await session.commit()
    return await _nation_edit_dto(session, nation)


async def _nation_delete_preview(session: AsyncSession, nation: Nation) -> dict:
    """
    The fixed-shape delete-preview response for one nation (0.11.0
    unit 8c): the nation's identity, its owner, the provinces it
    holds (display names through the province-info hooks, ordered by
    name) and the merged ``consequences`` — every registered
    nation-preview hook contributes ready Russian sentences of what
    the deletion touches in its own tables.

    A failing hook propagates: a wrong preview must never authorize
    a real deletion (the same rule as the player preview). Read-only,
    never commits.
    """
    owner = (
        await session.execute(select(Player).where(Player.id == nation.owner_player_id))
    ).scalar_one()
    province_ids = list(
        (
            await session.execute(
                select(Province.id).where(Province.nation_id == nation.id)
            )
        ).scalars()
    )
    info = await _collect_province_info(session, province_ids)
    provinces = sorted(
        ({"id": pid, "name": info.get(pid, {}).get("name")} for pid in province_ids),
        key=lambda item: ((item["name"] or "").casefold(), item["id"]),
    )
    names = await _display_names_by_vk(session, {owner.vk_user_id})
    consequences: list[dict] = []
    for preview_hook in AdminRegistry.get_nation_preview_hooks().values():
        consequences.extend(await preview_hook(session, nation.id))
    return {
        "nation_id": nation.id,
        "short_name": nation.short_name,
        "name": nation.name,
        "owner_vk_user_id": owner.vk_user_id,
        "owner_name": names.get(owner.vk_user_id),
        "provinces": provinces,
        "consequences": consequences,
    }


@router.get("/nations/{nation_id}/delete-preview")
async def admin_nation_delete_preview(
    nation_id: str,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    What deleting this nation would do — read-only, never commits.

    The consequence lines come from the same module hooks whose data
    the real deletion detaches, so a positive preview is an honest
    statement of the destructive operation. 404 NATION_NOT_FOUND for
    unknown ids.
    """
    nation = (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(nation_id)
    return await _nation_delete_preview(session, nation)


@router.post("/nations/{nation_id}/delete")
async def admin_nation_delete(
    nation_id: str,
    body: NationDeleteRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Delete a nation — irreversible; the owner stays a player and may
    register a new nation.

    Guards, in order: the nation must exist (404 NATION_NOT_FOUND);
    the retyped ``confirm_short_name`` must equal the nation's short
    name after trimming, case-sensitive (422 CONFIRMATION_MISMATCH).

    The deletion itself is the unchanged ``NationService.delete`` on
    the request session — one transaction, all-or-nothing: provinces
    freed, scheduled actions orphaned, the release entries written to
    the map's ownership journal, then the nation row. Any failure
    rolls everything back and answers 500 NATION_DELETE_FAILED. One
    ``nation.delete`` journal row lands before the commit, plus a
    WARNING audit line; the answer returns the preview that was true
    at the moment of deletion.
    """
    nation = (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(nation_id)
    if (
        body.confirm_short_name is None
        or str(body.confirm_short_name).strip() != nation.short_name
    ):
        raise ConfirmationMismatchError()

    owner = (
        await session.execute(select(Player).where(Player.id == nation.owner_player_id))
    ).scalar_one()
    owner_subject = await _admin_subject(session, owner)
    # Snapshot the values the audit row and the answer need — the
    # nation row is gone after NationService.delete flushes.
    short_name = nation.short_name
    owner_player_id = nation.owner_player_id
    preview = await _nation_delete_preview(session, nation)
    # The preview orders provinces by display name; the audit details
    # keep the plain id order, same as nation.create's details.
    province_ids = sorted(item["id"] for item in preview["provinces"])
    try:
        await NationService.delete(session, nation.id)
    except Exception as exc:
        await session.rollback()
        logger.exception("Admin nation delete failed for nation_id %s", nation_id)
        raise NationDeleteFailedError(exc) from exc

    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="nation.delete",
        target_type="nation",
        target_id=nation_id,
        summary=(
            f"Удалено государство «{short_name}» игрока {owner_subject}; "
            f"провинций освобождено: {len(province_ids)}."
        ),
        details={
            "nation_id": nation_id,
            "owner_player_id": owner_player_id,
            "owner_vk_user_id": owner.vk_user_id,
            "province_ids": province_ids,
        },
    )
    await session.commit()
    logger.warning(
        "admin_nation_delete admin_vk_user_id=%s nation_id=%s provinces_released=%s",
        admin.vk_user_id,
        nation_id,
        len(province_ids),
    )
    return preview


async def _load_nation_or_404(session: AsyncSession, nation_id: str) -> Nation:
    """The nation row or 404 NATION_NOT_FOUND."""
    nation = (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(nation_id)
    return nation


async def _nation_image_dto(
    session: AsyncSession, nation: Nation, kind: str, info
) -> dict:
    """The delete-preview/delete answer of one nation picture (0.12.0
    unit 8): the identity, the upload stamp, the uploader and the
    «Что будет» consequence lines of mockup 18b — the data as it was
    true at the moment of the call (or of the deletion)."""
    return {
        "nation_id": nation.id,
        "short_name": nation.short_name,
        "kind": kind,
        "uploaded_at": _iso_utc(info.uploaded_at),
        "uploaded_by": await _image_uploaded_by(session, info.uploaded_by_player_id),
        "consequences": [
            {"code": "image_deleted", "text": _IMAGE_DELETE_CONSEQUENCES[kind]},
            {"code": "audit_journal", "text": _IMAGE_DELETE_AUDIT_LINE},
        ],
    }


@router.get("/nations/{nation_id}/images/{kind}/delete-preview")
async def admin_nation_image_delete_preview(
    nation_id: str,
    kind: str,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    What deleting this nation's ``kind`` picture would do — read-only,
    never commits (0.12.0 unit 8).

    ``kind`` outside flag/portrait answers a bare 404; unknown nation
    -> 404 NATION_NOT_FOUND; a nation without such a picture -> 404
    IMAGE_NOT_FOUND.
    """
    if kind not in _IMAGE_KINDS:
        raise HTTPException(status_code=404)
    nation = await _load_nation_or_404(session, nation_id)
    info = (await NationService.image_info(session, nation_id))[kind]
    if info is None:
        raise ImageNotFoundError(f"nation {nation_id} has no {kind} image")
    return await _nation_image_dto(session, nation, kind, info)


@router.post("/nations/{nation_id}/images/{kind}/delete")
async def admin_nation_image_delete(
    nation_id: str,
    kind: str,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Delete one uploaded picture of a nation — irreversible; the empty
    body needs no retyped confirmation (the confirmation lives in the
    separate window of mockup 18b).

    Same 404 cases as the preview. ONE transaction: the row deletion
    inside NationService.delete_image, one ``nation_image_delete``
    journal row (ids and the first 12 sha256 characters only, never
    bytes), then the commit — plus a WARNING audit line. The answer is
    the preview shape as it was true at the moment of deletion; a
    second call finds no row and answers 404 IMAGE_NOT_FOUND without
    touching the journal.
    """
    if kind not in _IMAGE_KINDS:
        raise HTTPException(status_code=404)
    nation = await _load_nation_or_404(session, nation_id)
    removed = await NationService.delete_image(session, nation_id, kind)
    if removed is None:
        raise ImageNotFoundError(f"nation {nation_id} has no {kind} image")

    answer = await _nation_image_dto(session, nation, kind, removed.info)
    kind_word = "флаг" if kind == "flag" else "портрет"
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="nation_image_delete",
        target_type="nation",
        target_id=nation_id,
        summary=f"Удалён {kind_word} государства «{nation.short_name}».",
        details={
            "nation_id": nation_id,
            "kind": kind,
            "sha256_prefix": removed.sha256[:12],
        },
    )
    await session.commit()
    logger.warning(
        "admin_nation_image_delete admin_vk_user_id=%s nation_id=%s kind=%s",
        admin.vk_user_id,
        nation_id,
        kind,
    )
    return answer


@router.get("/overview")
async def admin_overview(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """
    The «Состояние мира» tiles: every module's overview hook contributes
    its own list of {"key", "label", "value", "sort"} — values already
    formatted for display, never raw JSON.

    The merged answer is sorted by `sort` (a stable sort keeps the
    registration order inside equal keys). A failing hook is logged,
    its session rolled back and its tiles skipped — it never breaks the
    response, same rule as the state views.
    """
    tiles: list[dict] = []
    for slug, overview_hook in AdminRegistry.get_overview_hooks().items():
        try:
            tiles.extend(await overview_hook(session))
        except Exception:
            logger.exception("Admin overview hook failed for '%s'", slug)
            await session.rollback()
    return sorted(tiles, key=lambda tile: tile["sort"])


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
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    result = await session.execute(
        select(TickLog).order_by(TickLog.id.desc()).limit(limit)
    )
    return [_tick_log_dict(row, config) for row in result.scalars().all()]


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
    # rollback() expires the admin object, so snapshot the vk id now —
    # reading it afterwards would need a lazy refresh (no async lazy).
    admin_vk_id = admin.vk_user_id
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
    # One audit row on the request session, committed separately from
    # the tick's own transaction: the journal records the action even
    # when the tick itself failed and was rolled back.
    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin_vk_id,
        action="tick.run",
        summary=(
            f"Запущен ход вручную: мир на ходе {clock.current_turn}."
            if ok
            else "Запущен ход вручную: тик завершился ошибкой."
        ),
        details={"ok": ok, "current_turn": clock.current_turn},
    )
    await session.commit()
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    return {
        "ok": ok,
        "current_turn": clock.current_turn,
        "next_tick_at": format_game_time(clock.next_tick_at, config.tick.tick_timezone),
        "tick_log": (
            _tick_log_dict(latest_log, config) if latest_log is not None else None
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

    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="world.reset",
        summary="Выполнен сброс состояния мира.",
        details={"reset": plan},
    )
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
    caller's own player (409 CANNOT_DELETE_SELF) nor any admin — env
    allowlist or admin_grants row (409 CANNOT_DELETE_ADMIN); the retyped
    confirm_vk_user_id must match the path id (422 CONFIRMATION_MISMATCH).

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
    if await is_admin_user(session, player.vk_user_id):
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

    await AdminAuditService.record(
        session,
        actor_vk_user_id=admin.vk_user_id,
        action="player.delete",
        target_type="player",
        target_id=str(vk_user_id),
        summary=f"Удалён игрок {vk_user_id}.",
        details=preview,
    )
    await session.commit()
    logger.warning(
        "admin_player_delete admin_vk_user_id=%s target_vk_user_id=%s counts=%s",
        admin.vk_user_id,
        vk_user_id,
        preview,
    )
    return preview


async def _display_names_by_vk(
    session: AsyncSession, vk_user_ids: set[int]
) -> dict[int, str]:
    """
    {vk_user_id: display_name} for the vk ids that still belong to a
    player, resolved through the player-info hooks (unit 6b). A vk id
    with no living player — or no module-provided name — is simply
    absent from the answer, so callers fall back to the id itself.
    """
    if not vk_user_ids:
        return {}
    rows = (
        await session.execute(
            select(Player.id, Player.vk_user_id).where(
                Player.vk_user_id.in_(vk_user_ids)
            )
        )
    ).all()
    if not rows:
        return {}
    info = await _collect_player_info(session, [row.id for row in rows])
    return {
        row.vk_user_id: info[row.id]["display_name"]
        for row in rows
        if info.get(row.id, {}).get("display_name") is not None
    }


@router.get("/audit-log")
async def admin_audit_log(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    actor_vk_user_id: int | None = None,
    action: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_id: Annotated[int | None, Query(ge=1)] = None,
) -> dict:
    """
    One page of the bounded admin journal («Журнал», unit 7).

    Filters: ``actor_vk_user_id`` and ``action`` match exactly;
    ``date_from``/``date_to`` are 'YYYY-MM-DD' local calendar dates in
    the tick timezone, inclusive. ``before_id`` is the cursor — the
    answer's ``next_before_id`` (null at the last page) feeds it.
    ``retention_limit`` is the current ``admin_panel.audit_log_max_rows``
    — the caption under the table shows it.

    ``actor_name`` is the display name the player-info hooks know —
    null when the actor is no longer a player (the journal survives
    player deletion). ``action_label`` comes from the modules'
    audit-action registrations; an unregistered code stays raw.
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    rows = await AdminAuditService.list_recent(
        session,
        limit + 1,
        before_id=before_id,
        actor_vk_user_id=actor_vk_user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        tz_name=config.tick.tick_timezone,
    )
    items = rows[:limit]
    labels = AdminRegistry.get_audit_action_labels()
    names = await _display_names_by_vk(session, {row.actor_vk_user_id for row in items})
    return {
        "items": [
            {
                "id": row.id,
                "created_at": format_game_time(
                    row.created_at, config.tick.tick_timezone
                ),
                "actor_vk_user_id": row.actor_vk_user_id,
                "actor_name": names.get(row.actor_vk_user_id),
                "action": row.action,
                "action_label": labels.get(row.action, row.action),
                "target_type": row.target_type,
                "target_id": row.target_id,
                "summary": row.summary,
            }
            for row in items
        ],
        "next_before_id": items[-1].id if len(rows) > limit else None,
        "retention_limit": config.admin_panel.audit_log_max_rows,
    }


@router.get("/audit-log/filters")
async def admin_audit_log_filters(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    The dropdown values of the journal filters: every actor vk id
    present in the journal (with a display name when the player still
    exists) and every action code with its registered label — unknown
    codes arrive raw, as in the log itself.
    """
    actors = await AdminAuditService.distinct_actors(session)
    actions = await AdminAuditService.distinct_actions(session)
    labels = AdminRegistry.get_audit_action_labels()
    names = await _display_names_by_vk(session, set(actors))
    return {
        "actors": [{"vk_user_id": vk, "display_name": names.get(vk)} for vk in actors],
        "actions": [
            {"action": code, "action_label": labels.get(code, code)} for code in actions
        ],
    }


@router.get("/admins")
async def admin_list_admins(
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """
    Everyone holding admin rights: the env allowlist first, then the
    granted players (a vk id on both shows only its env row — the
    environment wins). ``granted_by_vk_user_id`` is a plain snapshot —
    its ``granted_by_name`` resolves only while that vk id is still a
    player. ``is_self`` lets the panel grey out the caller's own row.
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    env_ids = _admin_vk_user_ids()
    grant_rows = (
        await session.execute(
            select(AdminGrant, Player)
            .join(Player, AdminGrant.player_id == Player.id)
            .order_by(AdminGrant.granted_at, AdminGrant.id)
        )
    ).all()

    vk_ids = set(env_ids)
    for grant, player in grant_rows:
        vk_ids.add(player.vk_user_id)
        if grant.granted_by_vk_user_id is not None:
            vk_ids.add(grant.granted_by_vk_user_id)
    names = await _display_names_by_vk(session, vk_ids)

    items: list[dict] = [
        {
            "vk_user_id": vk,
            "display_name": names.get(vk),
            "source": "env",
            "granted_by_vk_user_id": None,
            "granted_by_name": None,
            "granted_at": None,
            "is_self": vk == admin.vk_user_id,
        }
        for vk in sorted(env_ids)
    ]
    for grant, player in grant_rows:
        if player.vk_user_id in env_ids:
            continue
        items.append(
            {
                "vk_user_id": player.vk_user_id,
                "display_name": names.get(player.vk_user_id),
                "source": "grant",
                "granted_by_vk_user_id": grant.granted_by_vk_user_id,
                "granted_by_name": (
                    names.get(grant.granted_by_vk_user_id)
                    if grant.granted_by_vk_user_id is not None
                    else None
                ),
                "granted_at": format_game_time(
                    grant.granted_at, config.tick.tick_timezone
                ),
                "is_self": player.vk_user_id == admin.vk_user_id,
            }
        )
    return items


async def _admin_subject(session: AsyncSession, player: Player) -> str:
    """The audit-summary name of a player: its display name or the vk id."""
    names = await _display_names_by_vk(session, {player.vk_user_id})
    return names.get(player.vk_user_id, str(player.vk_user_id))


@router.post("/admins")
async def admin_grant_admin(
    body: AdminGrantRequest,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Grant admin rights to an existing player (unit 7).

    404 PLAYER_NOT_FOUND for an unknown vk id; idempotent for an
    already granted one. A grant that actually changes state writes
    one ``admin.grant`` journal row in the request transaction.
    """
    player = await _load_player_by_vk_id(session, body.vk_user_id)
    already = await AdminGrantService.is_granted(session, player.vk_user_id)
    await AdminGrantService.grant(session, player.id, by_vk_user_id=admin.vk_user_id)
    if not already:
        await AdminAuditService.record(
            session,
            actor_vk_user_id=admin.vk_user_id,
            action="admin.grant",
            target_type="player",
            target_id=str(body.vk_user_id),
            summary=(
                "Выданы права администратора игроку "
                f"{await _admin_subject(session, player)}."
            ),
            details={
                "player_id": player.id,
                "vk_user_id": body.vk_user_id,
            },
        )
    await session.commit()
    return {"granted": body.vk_user_id}


@router.post("/admins/{vk_user_id}/revoke")
async def admin_revoke_admin(
    vk_user_id: int,
    admin: Player = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """
    Revoke a player's admin rights (unit 7).

    The caller may never revoke themselves (409 CANNOT_REVOKE_SELF —
    checked before the service); the service itself refuses env
    admins (409 ROOT_ADMIN_PROTECTED) and the last remaining admin
    (409 LAST_ADMIN). A revoke that removes a real grant writes one
    ``admin.revoke`` journal row in the request transaction.
    """
    if vk_user_id == admin.vk_user_id:
        raise CannotRevokeSelfError()
    player = await _load_player_by_vk_id(session, vk_user_id)
    was_granted = await AdminGrantService.is_granted(session, player.vk_user_id)
    await AdminGrantService.revoke(session, player.id)
    if was_granted:
        await AdminAuditService.record(
            session,
            actor_vk_user_id=admin.vk_user_id,
            action="admin.revoke",
            target_type="player",
            target_id=str(vk_user_id),
            summary=(
                "Сняты права администратора у игрока "
                f"{await _admin_subject(session, player)}."
            ),
            details={
                "player_id": player.id,
                "vk_user_id": vk_user_id,
            },
        )
    await session.commit()
    return {"revoked": vk_user_id}


def _no_store_error(status_code: int, code: str, detail: str) -> JSONResponse:
    """An ErrorResponse-shaped answer with Cache-Control: no-store."""
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/panel-link")
async def admin_panel_link(
    response: Response,
    admin: Player = Depends(require_admin),
) -> dict:
    """
    Issue a one-time entry link for the admin panel (a ticket, no audit row).

    The token is random (secrets.token_urlsafe(32)); the store keeps only
    its SHA-256 hash, the player id and the expiry — never the token
    itself, never in logs. The client sends it to the panel tab inside
    the URL fragment, so it reaches neither server logs nor Referer.
    """
    settings = CoreConfig.from_yaml(CoreConfig.get_default_config_path()).admin_panel
    token = panel_access.store.issue(
        admin.id,
        ttl_seconds=settings.link_ttl_seconds,
        max_per_player=settings.max_pending_links_per_player,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"token": token, "expires_in_seconds": settings.link_ttl_seconds}


@router.post("/session")
async def admin_panel_session(
    body: PanelSessionRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Exchange a one-time link token for a short panel session — NO Bearer.

    redeem() marks the token spent before any await, so the exchange is
    atomic and unknown/expired/used tokens all answer the same 401
    PANEL_LINK_INVALID. The rights check is a fresh database read
    (is_admin_user): a player whose grant was revoked between issue and
    exchange gets 403 ADMIN_REQUIRED and the token stays spent. A
    successful exchange commits one panel.login audit row and issues an
    ordinary short Bearer JWT — require_admin serves it like any other.
    Every answer carries Cache-Control: no-store; failures log a WARNING
    without the token.
    """
    player_id = panel_access.store.redeem(body.token)
    if player_id is None:
        logger.warning("Admin panel session rejected: invalid one-time link")
        return _no_store_error(
            401, "PANEL_LINK_INVALID", "The panel link is invalid or expired"
        )

    player = await session.get(Player, player_id)
    if player is None or not await is_admin_user(session, player.vk_user_id):
        logger.warning(
            "Admin panel session rejected: player %s no longer holds admin rights",
            player_id,
        )
        return _no_store_error(403, "ADMIN_REQUIRED", "Admin privileges required")

    settings = CoreConfig.from_yaml(CoreConfig.get_default_config_path()).admin_panel
    await AdminAuditService.record(
        session,
        actor_vk_user_id=player.vk_user_id,
        action="panel.login",
        summary="Вход в панель администратора.",
    )
    access_token = issue_token(player.id, settings.session_ttl_minutes)
    await session.commit()
    return JSONResponse(
        {
            "access_token": access_token,
            "expires_in_seconds": settings.session_ttl_minutes * 60,
        },
        headers={"Cache-Control": "no-store"},
    )
