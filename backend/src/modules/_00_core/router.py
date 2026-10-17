"""
HTTP API router for module 00_core.

Implements the 8 endpoints from Spec Part 5. Auth is Bearer JWT resolved
via the shared get_current_player dependency; VK entry point validates
launch-params signatures.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from core.security.jwt import issue_token
from core.security.vk_signature import validate_launch_params
from modules._00_core.calendar import compute_game_date, format_game_date
from modules._00_core.catalog import flag_url, portrait_url
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import CoreDomainError, NationNotFoundError
from modules._00_core.models import GameClock, Nation, Player, Province
from modules._00_core.nation_enums import GENDERS, SUCCESSION_TYPES
from modules._00_core.schemas import (
    AuthResponseDTO,
    CatalogItemDTO,
    ColorCheckDTO,
    ColorCheckRequest,
    GameClockDTO,
    NationCreateRequest,
    NationDeleteRequest,
    NationDTO,
    NationRulesDTO,
    NationUpdateRequest,
    PlayerDTO,
    ProvinceDTO,
    VkAuthRequest,
)
from modules._00_core.service import NationService, PlayerService

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


async def _nation_dto(session: AsyncSession, nation: Nation) -> NationDTO:
    """Assemble NationDTO, including the nation's province IDs."""
    result = await session.execute(
        select(Province.id).where(Province.nation_id == nation.id).order_by(Province.id)
    )
    return NationDTO(
        id=nation.id,
        owner_player_id=nation.owner_player_id,
        created_at=nation.created_at,
        name=nation.name,
        short_name=nation.short_name,
        color_hex=nation.color_hex,
        motto=nation.motto,
        description=nation.description,
        flag_id=nation.flag_id,
        flag_url=flag_url(nation.flag_id),
        province_ids=list(result.scalars().all()),
        capital_province_id=nation.capital_province_id,
        capital_name=nation.capital_name,
        leader_name=nation.leader_name,
        gender=nation.gender,
        leader_title=nation.leader_title,
        leader_bio=nation.leader_bio,
        portrait_id=nation.portrait_id,
        portrait_url=portrait_url(nation.portrait_id),
        succession_type=nation.succession_type,
        history_url=nation.history_url,
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
        token_type="bearer",
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
        flags=[
            CatalogItemDTO(id=flag_id, url=flag_url(flag_id))
            for flag_id in CORE_CONFIG.catalog.flag_ids
        ],
        portraits=[
            CatalogItemDTO(id=portrait_id, url=portrait_url(portrait_id))
            for portrait_id in CORE_CONFIG.catalog.portrait_ids
        ],
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
        flag_id=body.flag_id,
        portrait_id=body.portrait_id,
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
        flag_id=body.flag_id,
        portrait_id=body.portrait_id,
        anthem_url=body.anthem_url,
        capital_name=body.capital_name,
        config=CORE_CONFIG,
    )
    await session.commit()
    return await _nation_dto(session, nation)


@router.delete("/nations/me", status_code=204)
async def delete_nations_me(
    body: NationDeleteRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete the authenticated player's nation and free its provinces."""
    nation = await _get_own_nation(session, player)
    await NationService.delete(session, nation_id=nation.id)
    await session.commit()
    return Response(status_code=204)


@router.get("/provinces", response_model=list[ProvinceDTO])
async def list_provinces(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
    ids: Annotated[list[int], Query()] = [],
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
