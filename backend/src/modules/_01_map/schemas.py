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


class MapNodeLabelDTO(BaseModel):
    """``MapNodeDTO.label`` (map2_6): anchor plus free ``w``/``h`` box.

    ``spine``/``len``/``thick`` (map2_20): the inscribed baseline the
    curved name rides — ``[x0, y0, x1, y1, s]`` endpoints plus signed
    sagitta, chord length and local thickness."""

    x: float
    y: float
    w: float
    h: float
    spine: list[float]
    len: float
    thick: float


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
    label: MapNodeLabelDTO


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


class MapBordersRulesDTO(BaseModel):
    """``MapViewRulesDTO.borders`` — client border-layer style (map2_4)."""

    internal_width: float
    internal_opacity: float
    internal_color: str
    state_width: float
    state_color: str
    coast_width: float
    coast_color: str


class MapSelectionRulesDTO(BaseModel):
    """``MapViewRulesDTO.selection`` — client selection style (map2_4)."""

    pulse_min_opacity: float
    pulse_max_opacity: float
    pulse_period_s: float
    picked_opacity: float


class MapReliefRulesDTO(BaseModel):
    """``MapViewRulesDTO.relief`` — client relief-underlay style (map2_16)."""

    enabled: bool
    strength_playable: float
    inactive_brightness: float


class MapLabelsRulesDTO(BaseModel):
    """``MapViewRulesDTO.labels`` — label fit/style rules (map2_6)."""

    font: str
    # map2_21: sea labels may use their own face from the font registry.
    sea_font: str
    land_min_px: int
    land_max_px: int
    sea_min_px: int
    sea_max_px: int
    fit_ratio: float
    collision_padding_px: float
    halo_width_px: float
    halo_color: str
    land_color: str
    sea_color: str
    sea_letter_spacing_em: float
    province_zoom_ratio: float
    fade_ms: int
    # map2_20: province names follow the shape (curved spine labels)
    max_angle_deg: float
    max_bend: float
    thickness_ratio: float
    length_ratio: float
    letter_spacing_min_em: float
    letter_spacing_max_em: float
    land_opacity: float
    sea_opacity: float
    sea_curved: bool


class MapStatesRulesDTO(BaseModel):
    """``MapViewRulesDTO.states`` — state-name layer rules (map2_7)."""

    font: str
    uppercase: bool
    opacity: float
    max_angle_deg: float
    thickness_ratio: float
    length_ratio: float
    max_letter_spacing_em: float
    max_bend: float
    min_px: int
    max_px: int
    color_mode: str
    min_group_share: float


class MapViewRulesDTO(BaseModel):
    """``MapManifestDTO.rules`` — client-side view rules from the config."""

    # [x, y, width, height] in view_box units (Spec 1.9).
    frame: list[float]
    zoom_max: float
    pan_margin_fraction: float
    label_min_width_px: int
    search_min_chars: int
    search_max_results: int
    colors: dict[str, str]
    hover_fill_opacity: float
    hover_stroke_enabled: bool
    borders: MapBordersRulesDTO
    selection: MapSelectionRulesDTO
    relief: MapReliefRulesDTO
    labels: MapLabelsRulesDTO
    states: MapStatesRulesDTO
    require_connected_start: bool
    big_window_enabled: bool
    refresh: MapRefreshRulesDTO


class MapManifestDTO(BaseModel):
    """Response for GET /api/v1/map/manifest."""

    schema_version: int
    geometry_version: str
    borders_version: str
    view_box: list[float]
    playable_bbox: list[float]
    nodes: list[MapNodeDTO]
    edges: list[MapEdgeDTO]
    rules: MapViewRulesDTO
    attribution: str


class MapProvinceNamesDTO(BaseModel):
    """
    Response for GET /api/v1/map/province-names (load-speed unit 11).

    The light names-only payload for screens that need province names
    but not the map itself: ``map_version`` is the manifest's
    ``geometry_version`` string, ``names`` maps every node id to its
    display name (``name_ru`` when set, else ``name``, else the node
    key — the same rule ``MapNode.display_name`` applies). No geometry,
    coordinates or edges.
    """

    map_version: str
    names: dict[int, str]


class MapGeometryDTO(BaseModel):
    """Response for GET /api/v1/map/geometry/{version}."""

    version: str
    paths: dict[int, str]
    outside: str
    sea_water: str


class MapBordersDTO(BaseModel):
    """Response for GET /api/v1/map/borders/{version} (map2_1B)."""

    version: str
    pairs: dict[str, str]
    coasts: dict[str, str]


class MapNationDTO(BaseModel):
    """
    One nation referenced by ``MapStateDTO.owners``.

    ``id`` is ``None`` for nations that no longer exist in the live
    table (possible only in past-turn answers); ``name``/
    ``short_name``/``color_hex`` are always the values recorded at the
    described turn.
    """

    id: uuid.UUID | None
    name: str
    short_name: str
    color_hex: str


class MapStateDTO(BaseModel):
    """Response for GET /api/v1/map/state."""

    geometry_version: str
    borders_version: str
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
