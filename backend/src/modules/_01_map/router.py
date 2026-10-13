"""
HTTP API router for module 01_map (Spec Part 5).

Four endpoints under /api/v1/map, all behind the shared Bearer JWT
dependency. Manifest and geometry bodies are prebuilt bytes from the
installed MapService (see api_service.py); state is assembled per
request inside the request's read transaction. The removed reserve pass
endpoints (Spec 1.6) intentionally do not exist — they answer 404 by
absence of the route.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security.dependencies import get_current_player
from modules._00_core.models import Player
from modules._01_map import api_service
from modules._01_map.errors import MapVersionUnknownError
from modules._01_map.schemas import (
    MapBordersDTO,
    MapGeometryDTO,
    MapManifestDTO,
    MapStateDTO,
    StartingGroupCheckRequest,
    StartingGroupCheckResponse,
)
from modules._01_map.service import get_map_service

router = APIRouter(prefix="/api/v1")

# The manifest changes rarely but the client revalidates every time —
# it must not be cached without a conditional request (3.10).
_MANIFEST_HEADERS = {"Cache-Control": "no-cache"}

# The geometry and borders bodies are immutable per version — the
# version IS the ETag.
_IMMUTABLE_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
}


@router.get(
    "/map/manifest",
    response_model=MapManifestDTO,
    responses={304: {"description": "Not Modified — ETag still matches"}},
)
async def get_map_manifest(
    player: Player = Depends(get_current_player),
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    """The node/edge manifest plus client view rules, with ETag/304."""
    payloads = api_service.get_api_payloads()
    headers = {**_MANIFEST_HEADERS, "ETag": payloads.manifest_etag}
    if api_service.etag_matches(if_none_match, payloads.manifest_etag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=payloads.manifest_body,
        media_type="application/json",
        headers=headers,
    )


@router.get(
    "/map/geometry/{version}",
    response_model=MapGeometryDTO,
)
async def get_map_geometry(
    version: str,
    player: Player = Depends(get_current_player),
) -> Response:
    """
    Immutable geometry of one version; any other version ->
    MAP_VERSION_UNKNOWN (the client re-requests the manifest).
    """
    payloads = api_service.get_api_payloads()
    if version != payloads.geometry_version:
        raise MapVersionUnknownError(version)
    return Response(
        content=payloads.geometry_body,
        media_type="application/json",
        headers={
            **_IMMUTABLE_HEADERS,
            "ETag": f'"{payloads.geometry_version}"',
        },
    )


@router.get(
    "/map/borders/{version}",
    response_model=MapBordersDTO,
)
async def get_map_borders(
    version: str,
    player: Player = Depends(get_current_player),
) -> Response:
    """
    Immutable shared borders/coasts of one version (map2_1B); any
    other version -> MAP_VERSION_UNKNOWN (the client re-requests the
    manifest).
    """
    payloads = api_service.get_api_payloads()
    if version != payloads.borders_version:
        raise MapVersionUnknownError(version)
    return Response(
        content=payloads.borders_body,
        media_type="application/json",
        headers={
            **_IMMUTABLE_HEADERS,
            "ETag": f'"{payloads.borders_version}"',
        },
    )


@router.get("/map/state", response_model=MapStateDTO)
async def get_map_state(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
    turn: Annotated[int | None, Query()] = None,
) -> MapStateDTO:
    """
    Owners of the current turn (live tables) or of a past turn
    (ownership journal). Out-of-range -> 422 TURN_OUT_OF_RANGE.
    """
    return await api_service.build_state(
        session, get_map_service(), turn
    )


@router.post(
    "/map/starting-group/check",
    response_model=StartingGroupCheckResponse,
)
async def post_starting_group_check(
    body: StartingGroupCheckRequest,
    player: Player = Depends(get_current_player),
) -> StartingGroupCheckResponse:
    """Connectivity of a would-be starting group (Spec 3.3)."""
    return api_service.check_starting_group(
        get_map_service(), body.province_ids
    )
