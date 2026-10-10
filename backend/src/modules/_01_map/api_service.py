"""
API assembly layer of 01_map (Spec Part 5).

The two heavy response bodies — the manifest DTO (~1.1k nodes, ~3.2k
edges on the real map) and the geometry JSON (~1.9 MB) — are built ONCE
per installed ``MapService`` and served as prepared bytes; the manifest
``ETag`` (strong, quoted) is computed alongside them (Spec 1.7: the tag
covers ``geometry_version``, the ``manifest.json`` hash AND the
canonical JSON of ``rules``, so a config-only edit changes it). The
lifespan calls :func:`get_api_payloads` right after ``startup_map()``
installs the service, so everything exists before the first request;
the lazy rebuild also keeps tests that swap the service singleton
correct.

The same file assembles ``/map/state`` answers — current owners come
from the live tables through ``00_core`` public services, past turns
from the ownership journal (formula 3.5) — and the starting-group
connectivity check. The API layer holds no business rules itself:
connectivity is ``MapService.group_components``, owner-at-turn is
``ownership_service.owners_at_turn``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.exceptions import (
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
)
from modules._00_core.service import (
    GameClockService,
    NationService,
    ProvinceService,
)
from modules._01_map.errors import (
    ProvinceNotLandError,
    TurnOutOfRangeError,
)
from modules._01_map.schemas import (
    MapBordersDTO,
    MapEdgeDTO,
    MapManifestDTO,
    MapNationDTO,
    MapNodeDTO,
    MapRefreshRulesDTO,
    MapStateDTO,
    MapViewRulesDTO,
    StartingGroupCheckResponse,
)
from modules._01_map.service import (
    MapService,
    NodeNotLandError,
    UnknownNodeError,
    get_map_service,
    owners_at_turn,
)


@dataclass(frozen=True)
class MapApiPayloads:
    """
    Prebuilt wire data of the /map/manifest and /map/geometry routes.

    ``manifest_etag`` is the strong, quoted entity-tag; both bodies are
    serialized once and reused for every request.
    """

    manifest_etag: str
    manifest_body: bytes
    geometry_version: str
    geometry_body: bytes
    borders_version: str
    borders_body: bytes
    node_count: int


def _rules_dto(service: MapService) -> MapViewRulesDTO:
    """MapViewRulesDTO straight from MapConfig — no literals."""
    config = service._config  # same package: the service's own config
    return MapViewRulesDTO(
        frame=[
            config.view.frame.x,
            config.view.frame.y,
            config.view.frame.width,
            config.view.frame.height,
        ],
        zoom_max=config.view.zoom_max,
        pan_margin_fraction=config.view.pan_margin_fraction,
        label_min_width_px=config.view.label_min_width_px,
        search_min_chars=config.view.search_min_chars,
        search_max_results=config.view.search_max_results,
        colors={
            "neutral_province": config.colors.neutral_province,
            "sea": config.colors.sea,
            "outside": config.colors.outside,
            "inland_water": config.colors.inland_water,
            "province_border": config.colors.province_border,
            "hover": config.colors.hover,
            "selected": config.colors.selected,
        },
        hover_fill_opacity=config.hover.fill_opacity,
        hover_stroke_enabled=config.hover.stroke_enabled,
        require_connected_start=config.starting_group.require_connected,
        big_window_enabled=config.big_window.enabled,
        refresh=MapRefreshRulesDTO(
            tick_refresh_delay_seconds=(
                config.refresh.tick_refresh_delay_seconds
            ),
            tick_refresh_jitter_seconds=(
                config.refresh.tick_refresh_jitter_seconds
            ),
            retry_delay_seconds=config.refresh.retry_delay_seconds,
            max_retries=config.refresh.max_retries,
            stale_after_seconds=config.refresh.stale_after_seconds,
        ),
    )


def _manifest_etag(
    geometry_version: str,
    manifest_sha256: str,
    rules: MapViewRulesDTO,
) -> str:
    """
    Spec Part 5 (1.7): first 16 hex of SHA-256 over the geometry
    version, the manifest file hash and the canonical JSON (sorted
    keys, no spaces) of the rules block. Returns a strong, quoted tag.
    """
    canon = json.dumps(
        {
            "geometry_version": geometry_version,
            "manifest_sha256": manifest_sha256,
            "rules": rules.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return '"' + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16] + '"'


def build_api_payloads(service: MapService) -> MapApiPayloads:
    """Build every precomputed payload from the loaded map + config."""
    data = service.map_data
    manifest = data.manifest
    rules = _rules_dto(service)

    nodes = [
        MapNodeDTO(
            id=node.id,
            key=node.key,
            kind=node.kind,
            # A schema-valid node always has a display name; the key is
            # the last-resort fallback (display_name rule, Spec Part 1).
            name=node.name or node.key,
            name_ru=node.name_ru,
            anchor=list(node.anchor),
            bbox=list(node.bbox),
            area=node.area,
        )
        for node in data.nodes.values()  # already ascending id order
    ]
    edges = [
        MapEdgeDTO(
            a=edge.a,
            b=edge.b,
            type=edge.type,
            name=edge.name,
            # FINAL strait crossing multiplier (Spec 3.11); the manifest
            # field `len` is not exposed.
            multiplier=service.strait_multiplier(edge.a, edge.b),
        )
        for edge in sorted(data.edges.values(), key=lambda e: (e.a, e.b))
    ]
    dto = MapManifestDTO(
        schema_version=manifest.schema_version,
        geometry_version=data.geometry_version,
        borders_version=data.borders_version,
        view_box=list(manifest.view_box),
        playable_bbox=list(manifest.playable_bbox),
        nodes=nodes,
        edges=edges,
        rules=rules,
        attribution=service._config.attribution.text,
    )
    geometry = data.geometry
    geometry_body = json.dumps(
        {
            "version": geometry.version,
            "paths": dict(geometry.paths),
            "outside": geometry.outside,
            "sea_water": geometry.sea_water,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    borders = data.borders
    borders_body = json.dumps(
        {
            "version": borders.version,
            "pairs": dict(borders.pairs),
            "coasts": dict(borders.coasts),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    return MapApiPayloads(
        manifest_etag=_manifest_etag(
            data.geometry_version, data.manifest_sha256, rules
        ),
        manifest_body=dto.model_dump_json().encode("utf-8"),
        geometry_version=data.geometry_version,
        geometry_body=geometry_body,
        borders_version=data.borders_version,
        borders_body=borders_body,
        node_count=len(data.nodes),
    )


# ---------------------------------------------------------- singleton

_payloads: MapApiPayloads | None = None
_payloads_service: MapService | None = None


def get_api_payloads() -> MapApiPayloads:
    """
    The payloads of the installed MapService — built at startup (the
    lifespan calls this right after ``startup_map()``) and rebuilt only
    when the service singleton is replaced (repeated boots, tests).
    """
    global _payloads, _payloads_service
    service = get_map_service()
    if _payloads is None or _payloads_service is not service:
        _payloads = build_api_payloads(service)
        _payloads_service = service
    return _payloads


def etag_matches(if_none_match: str | None, etag: str) -> bool:
    """
    ``If-None-Match`` evaluation (RFC 9110 weak comparison): a
    comma-separated list of entity-tags, an optional ``W/`` prefix and
    the ``*`` wildcard are all supported.
    """
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


# ------------------------------------------------------------- /state


async def build_state(
    session: AsyncSession, service: MapService, turn: int | None
) -> MapStateDTO:
    """
    Assemble MapStateDTO inside the caller's read transaction.

    ``turn`` absent or equal to the current turn -> live tables (owner
    data straight from provinces/nations); ``0 <= turn < current`` ->
    the ownership journal (names/colours recorded at event time, the
    ``id`` of a since-deleted nation becomes null); anything else ->
    TURN_OUT_OF_RANGE.
    """
    current = await GameClockService.current_turn(session)

    # (province_id, journal nation id, dto nation id, name, color) —
    # the journal id stays in the dedup key even when the nation is
    # gone, so two vanished look-alikes never merge (Spec Part 5).
    # Retired/absent nodes (id not in the active manifest) never appear
    # in the answer — live rows or journal snapshot alike (Spec 1.9:
    # ``GET /map/state`` does not return owners of withdrawn nodes).
    active_ids = service.map_data.nodes
    entries: list[tuple[int, str, str | None, str, str]] = []
    if turn is None or turn == current:
        described = current
        for row in await ProvinceService.list_current_owners(session):
            if row.province_id not in active_ids:
                continue
            entries.append(
                (
                    row.province_id,
                    row.nation_id,
                    row.nation_id,
                    row.nation_name,
                    row.nation_color,
                )
            )
    elif 0 <= turn < current:
        described = turn
        snapshot = await owners_at_turn(session, turn)
        existing = await NationService.existing_ids(
            session, {o.nation_id for o in snapshot.values()}
        )
        for province_id, owner in sorted(snapshot.items()):
            if province_id not in active_ids:
                continue
            entries.append(
                (
                    province_id,
                    owner.nation_id,
                    (
                        owner.nation_id
                        if owner.nation_id in existing
                        else None
                    ),
                    owner.name,
                    owner.color,
                )
            )
    else:
        raise TurnOutOfRangeError(turn, current)

    nations: list[MapNationDTO] = []
    nation_index: dict[tuple[str, str, str], int] = {}
    owners: list[list[int]] = []
    for province_id, log_id, dto_id, name, color in entries:
        key = (log_id, name, color)
        index = nation_index.get(key)
        if index is None:
            index = len(nations)
            nation_index[key] = index
            nations.append(
                MapNationDTO(id=dto_id, name=name, color_hex=color)
            )
        owners.append([province_id, index])

    return MapStateDTO(
        geometry_version=service.geometry_version,
        borders_version=service.borders_version,
        turn=described,
        nations=nations,
        owners=owners,
    )


# ------------------------------------------------- starting-group

def check_starting_group(
    service: MapService, province_ids: list[int]
) -> StartingGroupCheckResponse:
    """
    Real connectivity of the given LAND nodes (Spec 3.3) — reported
    even when ``starting_group.require_connected`` is off; the client
    decides what to do with the answer.

    The list is capped at the node count of the loaded map; unknown ids
    map to the core PROVINCE_NOT_FOUND (404), sea ids to
    PROVINCE_NOT_LAND (422). Duplicates are ignored by
    ``group_components``.
    """
    node_count = len(service.map_data.nodes)
    if len(province_ids) > node_count:
        raise ProvinceCountOutOfRangeError(
            len(province_ids), 1, node_count
        )
    try:
        components = service.group_components(province_ids)
    except UnknownNodeError as exc:
        raise ProvinceNotFoundError(exc.what) from exc
    except NodeNotLandError as exc:
        raise ProvinceNotLandError([exc.node_id]) from exc
    return StartingGroupCheckResponse(
        connected=len(components) == 1,
        component_count=len(components),
    )
