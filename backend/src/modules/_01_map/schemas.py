"""
API DTOs for module 01_map (Spec Part 5).

Request/response schemas of ``/api/v1/map/*``. ``MapManifestDTO`` and
``MapGeometryDTO`` are documented on the routes via ``response_model``,
but their bodies are prebuilt once per boot in ``api_service.py`` and
served as raw bytes — the models are the contract, not the serializer.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class MapNodeDTO(BaseModel):
    """One map node in ``MapManifestDTO.nodes``."""

    id: int
    key: str
    kind: Literal["LAND", "SEA"]
    name: str
    name_ru: str | None
    anchor: list[float]
    bbox: list[float]
    area: float


class MapEdgeDTO(BaseModel):
    """
    One adjacency in ``MapManifestDTO.edges``.

    ``multiplier`` is the FINAL value for ``strait`` edges (explicit or
    ``strait.default_crossing_multiplier``), ``None`` for other types;
    the manifest field ``len`` is never exposed.
    """

    a: int
    b: int
    type: Literal["land", "coast", "sea", "strait"]
    name: str | None
    multiplier: float | None


class MapRefreshRulesDTO(BaseModel):
    """``MapViewRulesDTO.refresh`` — the client refresh schedule (3.10)."""

    tick_refresh_delay_seconds: int
    tick_refresh_jitter_seconds: int
    retry_delay_seconds: int
    max_retries: int
    stale_after_seconds: int


class MapViewRulesDTO(BaseModel):
    """``MapManifestDTO.rules`` — client-side view rules from the config."""

    zoom_min: float
    zoom_max: float
    pan_margin_fraction: float
    label_min_width_px: int
    search_min_chars: int
    search_max_results: int
    colors: dict[str, str]
    require_connected_start: bool
    big_window_enabled: bool
    refresh: MapRefreshRulesDTO


class MapManifestDTO(BaseModel):
    """Response for GET /api/v1/map/manifest."""

    schema_version: int
    geometry_version: str
    view_box: list[float]
    playable_bbox: list[float]
    nodes: list[MapNodeDTO]
    edges: list[MapEdgeDTO]
    rules: MapViewRulesDTO
    attribution: str


class MapGeometryDTO(BaseModel):
    """Response for GET /api/v1/map/geometry/{version}."""

    version: str
    paths: dict[int, str]
    outside: str


class MapNationDTO(BaseModel):
    """
    One nation referenced by ``MapStateDTO.owners``.

    ``id`` is ``None`` for nations that no longer exist in the live
    table (possible only in past-turn answers); ``name``/``color_hex``
    are always the values recorded at the described turn.
    """

    id: uuid.UUID | None
    name: str
    color_hex: str


class MapStateDTO(BaseModel):
    """Response for GET /api/v1/map/state."""

    geometry_version: str
    turn: int
    nations: list[MapNationDTO]
    # [province_id, index into nations]; free provinces and SEA nodes
    # are never listed.
    owners: list[list[int]]


class StartingGroupCheckRequest(BaseModel):
    """Request body for POST /api/v1/map/starting-group/check."""

    province_ids: list[int] = Field(min_length=1)


class StartingGroupCheckResponse(BaseModel):
    """Response for POST /api/v1/map/starting-group/check."""

    connected: bool
    component_count: int
