"""
HTTP API router for module 00_core.

Implements the 8 endpoints from Spec Part 5. Auth is Bearer JWT resolved
via the shared get_current_player dependency; VK entry point validates
launch-params signatures.
"""

from __future__ import annotations

import os
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from core.db import get_session
from core.security.dependencies import get_current_player
from core.security.jwt import issue_token
from core.security.vk_signature import validate_launch_params
from modules._00_core import images
from modules._00_core.calendar import compute_game_date, format_game_date
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    CoreDomainError,
    ImageTooLargeError,
    NationNotFoundError,
)
from modules._00_core.models import GameClock, Nation, Player, Province
from modules._00_core.nation_enums import GENDERS, SUCCESSION_TYPES
from modules._00_core.schemas import (
    AuthResponseDTO,
    ColorCheckDTO,
    ColorCheckRequest,
    GameClockDTO,
    NationCreateRequest,
    NationDTO,
    NationImageDTO,
    NationPublicDTO,
    NationRulesDTO,
    NationRulesImagesDTO,
    NationUpdateRequest,
    PlayerDTO,
    ProvinceDTO,
    VkAuthRequest,
)
from modules._00_core.service import (
    NationImageRefs,
    NationService,
    PlayerService,
)

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

router = APIRouter(prefix="/api/v1")


class GameClockNotFoundError(CoreDomainError):
    """Raised when the game_clock singleton row is missing."""

    def __init__(self):
        super().__init__(
            "Game clock is not initialized",
            "GAME_CLOCK_NOT_FOUND",
        )


def _player_dto(player: Player) -> PlayerDTO:
    return PlayerDTO(
        id=player.id,
        vk_user_id=player.vk_user_id,
        created_at=player.created_at,
    )


async def _nation_with_owner(session: AsyncSession, nation_id: str) -> Nation | None:
    """Fetch a nation together with its owner Player in one JOIN query —
    the owner's ``level``/``judge_rating`` ride the same row, so neither
    DTO issues per-field fetches."""
    result = await session.execute(
        select(Nation).options(joinedload(Nation.owner)).where(Nation.id == nation_id)
    )
    return result.unique().scalar_one_or_none()


def _nation_public_fields(
    nation: Nation, province_ids: list[int], image_refs: NationImageRefs
) -> dict:
    """
    The field set shared by ``NationDTO`` and ``NationPublicDTO`` — exactly
    the public contract of Spec Part 5. The owner must already be loaded
    on ``nation`` (``_nation_with_owner``); ``level``/``judge_rating`` are
    the owner Player's columns. Picture URLs are built only through
    ``images.image_url`` (INV-16) from the sha256 refs — None when the
    nation never uploaded that kind.
    """
    return {
        "id": nation.id,
        "created_at": nation.created_at,
        "name": nation.name,
        "short_name": nation.short_name,
        "color_hex": nation.color_hex,
        "motto": nation.motto,
        "description": nation.description,
        "flag_url": images.image_url(image_refs.flag_sha256, "full"),
        "flag_thumb_url": images.image_url(image_refs.flag_sha256, "thumb"),
        "province_ids": province_ids,
        "capital_province_id": nation.capital_province_id,
        "capital_name": nation.capital_name,
        "leader_name": nation.leader_name,
        "leader_title": nation.leader_title,
        "leader_bio": nation.leader_bio,
        "portrait_url": images.image_url(image_refs.portrait_sha256, "full"),
        "portrait_thumb_url": images.image_url(image_refs.portrait_sha256, "thumb"),
        "history_url": nation.history_url,
        "level": nation.owner.level,
        "judge_rating": nation.owner.judge_rating,
    }


async def _nation_dto(session: AsyncSession, nation: Nation) -> NationDTO:
    """Assemble NationDTO — the public field set plus the owner-only keys."""
    loaded = await _nation_with_owner(session, nation.id)
    if loaded is not None:
        nation = loaded
    result = await session.execute(
        select(Province.id).where(Province.nation_id == nation.id).order_by(Province.id)
    )
    refs = (await NationService.image_refs(session, [nation.id]))[nation.id]
    fields = _nation_public_fields(nation, list(result.scalars().all()), refs)
    return NationDTO(
        **fields,
        owner_player_id=nation.owner_player_id,
        gender=nation.gender,
        succession_type=nation.succession_type,
        anthem_url=nation.anthem_url,
    )


async def _get_own_nation(session: AsyncSession, player: Player) -> Nation:
    """Load the player's nation or raise NATION_NOT_FOUND."""
    result = await session.execute(
        select(Nation).where(Nation.owner_player_id == player.id)
    )
    nation = result.scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(player.id)
    return nation


@router.post("/auth/vk", response_model=AuthResponseDTO)
async def auth_vk(
    body: VkAuthRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponseDTO:
    """Authenticate via VK launch params and issue a Bearer JWT."""
    vk_user_id = validate_launch_params(
        body.launch_params,
        os.environ["VK_APP_SECRET"],
        CORE_CONFIG.auth.vk_ts_freshness_window_minutes,
    )
    player = await PlayerService.get_or_create(session, vk_user_id)
    await session.commit()

    ttl_minutes = CORE_CONFIG.auth.jwt_ttl_minutes
    return AuthResponseDTO(
        access_token=issue_token(player.id, ttl_minutes),
        token_type="bearer",  # noqa: S106
        expires_in=ttl_minutes * 60,
        player=_player_dto(player),
    )


@router.get("/players/me", response_model=PlayerDTO)
async def get_players_me(
    player: Player = Depends(get_current_player),
) -> PlayerDTO:
    """Return the authenticated player's profile."""
    return _player_dto(player)


@router.get("/nations/me", response_model=NationDTO)
async def get_nations_me(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> NationDTO:
    """Return the authenticated player's nation."""
    nation = await _get_own_nation(session, player)
    return await _nation_dto(session, nation)


@router.get("/nations/rules", response_model=NationRulesDTO)
async def get_nation_rules(
    player: Player = Depends(get_current_player),
) -> NationRulesDTO:
    """Serve the nation form limits and value sets for UI hints."""
    return NationRulesDTO(
        name_min_length=CORE_CONFIG.nation.nation_name_min_length,
        name_max_length=CORE_CONFIG.nation.nation_name_max_length,
        short_name_min_length=CORE_CONFIG.nation.short_name_min_length,
        short_name_max_length=CORE_CONFIG.nation.short_name_max_length,
        motto_max_length=CORE_CONFIG.nation.motto_max_length,
        description_max_length=CORE_CONFIG.nation.description_max_length,
        leader_name_min_length=CORE_CONFIG.nation.leader_name_min_length,
        leader_name_max_length=CORE_CONFIG.nation.leader_name_max_length,
        leader_title_min_length=CORE_CONFIG.nation.leader_title_min_length,
        leader_title_max_length=CORE_CONFIG.nation.leader_title_max_length,
        leader_bio_max_length=CORE_CONFIG.nation.leader_bio_max_length,
        capital_name_min_length=CORE_CONFIG.nation.capital_name_min_length,
        capital_name_max_length=CORE_CONFIG.nation.capital_name_max_length,
        history_url_max_length=CORE_CONFIG.nation.history_url_max_length,
        history_url_allowed_hosts=CORE_CONFIG.nation.history_url_allowed_hosts,
        anthem_url_max_length=CORE_CONFIG.nation.anthem_url_max_length,
        anthem_url_allowed_hosts=CORE_CONFIG.nation.anthem_url_allowed_hosts,
        min_provinces=CORE_CONFIG.nation.min_provinces_per_nation,
        max_provinces=CORE_CONFIG.nation.max_provinces_per_nation,
        palette=CORE_CONFIG.color.palette,
        images=NationRulesImagesDTO(
            flag_width=CORE_CONFIG.images.flag_width,
            flag_height=CORE_CONFIG.images.flag_height,
            portrait_width=CORE_CONFIG.images.portrait_width,
            portrait_height=CORE_CONFIG.images.portrait_height,
            max_upload_bytes=CORE_CONFIG.images.max_upload_bytes,
        ),
        genders=list(GENDERS),
        succession_types=list(SUCCESSION_TYPES),
    )


@router.post("/nations/color-check", response_model=ColorCheckDTO)
async def check_color(
    body: ColorCheckRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> ColorCheckDTO:
    """Hint the color-input UI with the Part 3 decision — no lock, no
    writes; the caller's own nation is excluded from the comparison."""
    nation = (
        await session.execute(
            select(Nation.id).where(Nation.owner_player_id == player.id)
        )
    ).scalar_one_or_none()
    return ColorCheckDTO(
        status=await NationService.color_status(
            session, body.color_hex, CORE_CONFIG, exclude_nation_id=nation
        )
    )


@router.get("/nations/{nation_id}", response_model=NationPublicDTO)
async def get_nation_public(
    nation_id: str,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> NationPublicDTO:
    """Return another nation's public fields (Bible §7).

    Declared after ``/nations/me``, ``/nations/rules`` and
    ``/nations/color-check`` so those fixed paths keep winning. The id is
    a plain ``str``: a malformed id simply matches no row and answers the
    same 404/NATION_NOT_FOUND as an unknown UUID — never a 422.
    """
    nation = await _nation_with_owner(session, nation_id)
    if nation is None:
        raise NationNotFoundError(nation_id)
    result = await session.execute(
        select(Province.id).where(Province.nation_id == nation.id).order_by(Province.id)
    )
    refs = (await NationService.image_refs(session, [nation.id]))[nation.id]
    return NationPublicDTO(
        **_nation_public_fields(nation, list(result.scalars().all()), refs)
    )


@router.post("/nations", response_model=NationDTO, status_code=201)
async def create_nation(
    body: NationCreateRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> NationDTO:
    """Create a nation for the authenticated player."""
    nation = await NationService.create(
        session,
        owner_player_id=player.id,
        name=body.name,
        color_hex=body.color_hex,
        province_ids=body.province_ids,
        config=CORE_CONFIG,
        leader_name=body.leader_name,
        leader_title=body.leader_title,
        history_url=body.history_url,
        short_name=body.short_name,
        gender=body.gender,
        succession_type=body.succession_type,
        capital_name=body.capital_name,
        capital_province_id=body.capital_province_id,
        motto=body.motto,
        description=body.description,
        leader_bio=body.leader_bio,
        anthem_url=body.anthem_url,
    )
    await session.commit()
    return await _nation_dto(session, nation)


@router.patch("/nations/me", response_model=NationDTO)
async def update_nations_me(
    body: NationUpdateRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> NationDTO:
    """Update the authenticated player's nation fields."""
    nation = await _get_own_nation(session, player)
    nation = await NationService.update(
        session,
        nation_id=nation.id,
        name=body.name,
        color_hex=body.color_hex,
        leader_name=body.leader_name,
        leader_title=body.leader_title,
        history_url=body.history_url,
        short_name=body.short_name,
        gender=body.gender,
        succession_type=body.succession_type,
        motto=body.motto,
        description=body.description,
        leader_bio=body.leader_bio,
        anthem_url=body.anthem_url,
        capital_name=body.capital_name,
        config=CORE_CONFIG,
    )
    await session.commit()
    return await _nation_dto(session, nation)


@router.get("/provinces", response_model=list[ProvinceDTO])
async def list_provinces(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
    ids: Annotated[list[int], Query()] = [],  # noqa: B006 — FastAPI convention, never mutated
    free_only: Annotated[bool, Query()] = False,
) -> list[ProvinceDTO]:
    """List provinces, optionally filtered by IDs and/or free status."""
    stmt = select(Province).order_by(Province.id)
    if ids:
        stmt = stmt.where(Province.id.in_(ids))
    if free_only:
        stmt = stmt.where(Province.nation_id.is_(None))
    result = await session.execute(stmt)
    return [
        ProvinceDTO(id=p.id, nation_id=p.nation_id, kind=p.kind)
        for p in result.scalars().all()
    ]


@router.get("/game-clock", response_model=GameClockDTO)
async def get_game_clock(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> GameClockDTO:
    """Return the current turn, derived game date, and next tick time."""
    result = await session.execute(select(GameClock).where(GameClock.id == 1))
    clock = result.scalar_one_or_none()
    if clock is None:
        raise GameClockNotFoundError()
    game_date = compute_game_date(clock.current_turn, CORE_CONFIG)
    return GameClockDTO(
        current_turn=clock.current_turn,
        game_date=game_date.isoformat(),
        game_date_text=format_game_date(game_date, CORE_CONFIG),
        next_tick_at=clock.next_tick_at,
    )


# ---------------------------------------------------------------------------
# Nation images (0.12.0 unit 5b): upload + public serving (Spec Part 5).
# ---------------------------------------------------------------------------

_IMAGE_KINDS = ("flag", "portrait")
_IMAGE_VARIANTS = ("full", "thumb")
_IMAGE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# A viewer's browser revalidates at most once a day; a replaced or
# deleted picture turns its old content-hash URL into a 404 that must
# never be cached.
_IMAGE_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}
_IMAGE_NOSTORE_HEADERS = {"Cache-Control": "no-store"}


async def _read_upload_body(request: Request, limit: int) -> bytes:
    """
    The raw upload body with a hard cutoff at ``limit`` — never
    ``await request.body()`` unbounded. The declared Content-Length is
    rejected first; a chunked or lying body is cut off mid-stream, the
    first chunk that pushes past the limit aborts the read.
    """
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = -1
        if declared > limit:
            raise ImageTooLargeError(
                f"declared body {declared} bytes exceeds "
                f"images.max_upload_bytes={limit}"
            )
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise ImageTooLargeError(f"body exceeds images.max_upload_bytes={limit}")
    return bytes(body)


@router.put("/nations/me/images/{kind}", response_model=NationImageDTO)
async def put_nation_image(
    kind: str,
    request: Request,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> NationImageDTO:
    """Accept the player's uploaded flag/portrait file (Spec «Загрузка»).

    Check order: a nation exists (404) -> the body cutoff (413) -> the
    content checks of ``process_image_async`` (415 / 413 / 422) -> one
    write transaction that re-checks the nation, replaces the row and
    commits. ``Content-Type`` and the file name are ignored by design.
    """
    if kind not in _IMAGE_KINDS:
        raise HTTPException(status_code=404)

    nation = await _get_own_nation(session, player)
    nation_id = nation.id
    player_id = player.id
    # The read transaction ends here: the pooled connection is released
    # before the body is read and the processing semaphore is awaited —
    # a slow upload must not starve the pool.
    await session.commit()

    raw = await _read_upload_body(request, CORE_CONFIG.images.max_upload_bytes)
    processed = await images.process_image_async(raw, kind, CORE_CONFIG.images)

    # ONE write transaction: the nation may have vanished while the file
    # was processed — the 404 check repeats inside the writing tx.
    nation = (
        await session.execute(select(Nation).where(Nation.id == nation_id))
    ).scalar_one_or_none()
    if nation is None:
        raise NationNotFoundError(nation_id)
    view = await NationService.replace_image(
        session, nation_id, player_id, kind, processed
    )
    await session.commit()
    return NationImageDTO(
        kind=kind,
        url=images.image_url(view.sha256, "full"),
        thumb_url=images.image_url(view.sha256, "thumb"),
    )


@router.get("/images/{sha256}/{variant}")
async def get_nation_image(
    sha256: str,
    variant: str,
    session: AsyncSession = Depends(get_session),
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """Serve a stored picture publicly by content hash (Spec «Раздача»).

    No Bearer token on purpose — a plain ``<img>`` tag sends no
    Authorization header, and the content is visible to every player.
    Anything that is not a 64-hex hash and a known variant is a 404 with
    ``no-store`` — the same response a deleted/replaced picture gets.
    """
    if _IMAGE_SHA256_RE.fullmatch(sha256) is None or variant not in _IMAGE_VARIANTS:
        return Response(status_code=404, headers=_IMAGE_NOSTORE_HEADERS)

    body = await NationService.image_bytes(session, sha256, variant)
    if body is None:
        return Response(status_code=404, headers=_IMAGE_NOSTORE_HEADERS)

    headers = {
        **_IMAGE_CACHE_HEADERS,
        "ETag": f'"{sha256}"',
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(if_none_match, f'"{sha256}"'):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="image/webp", headers=headers)


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    """``If-None-Match`` evaluation (weak comparison): a comma-separated
    list of entity-tags, an optional ``W/`` prefix and the ``*``
    wildcard. Local copy of the rule used by 01_map — the core never
    imports satellite modules."""
    if not if_none_match:
        return False
    for part in if_none_match.split(","):
        tag = part.strip()
        if tag == "*":
            return True
        if tag[:2] == "W/":
            tag = tag[2:].strip()
        if tag == etag:
            return True
    return False
