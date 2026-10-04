"""
Immutable runtime map objects (Spec 1.6, Part 1 — "Объект времени
выполнения").

Everything here is immutable: frozen dataclasses, tuples and
``MappingProxyType`` read-only mappings. Iteration order is by ascending
node id everywhere; adjacency lists are sorted by neighbour id.

Internal to module ``_01_map`` — other modules must go through
``service.py`` (see its docstring) and never import this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .map_files import Geometry, Manifest

KIND_LAND = "LAND"
KIND_SEA = "SEA"

EDGE_TYPE_LAND = "land"
EDGE_TYPE_COAST = "coast"
EDGE_TYPE_SEA = "sea"
EDGE_TYPE_STRAIT = "strait"
EDGE_TYPES: tuple[str, ...] = (
    EDGE_TYPE_LAND,
    EDGE_TYPE_COAST,
    EDGE_TYPE_SEA,
    EDGE_TYPE_STRAIT,
)

# Spec 3.3: group connectivity counts only these edge types.
GROUP_EDGE_TYPES: frozenset[str] = frozenset(
    {EDGE_TYPE_LAND, EDGE_TYPE_STRAIT}
)

NodeKind = Literal["LAND", "SEA"]
EdgeType = Literal["land", "coast", "sea", "strait"]


@dataclass(frozen=True)
class MapNode:
    """One map node — a land province or a sea zone."""

    id: int
    key: str
    kind: NodeKind
    name: str | None
    name_ru: str | None
    source_name: str | None
    anchor: tuple[float, float]
    bbox: tuple[float, float, float, float]
    area: float

    @property
    def display_name(self) -> str:
        """``name_ru`` when present, else the source ``name`` (Spec Part 1)."""
        return self.name_ru or self.name or self.key


@dataclass(frozen=True)
class MapEdge:
    """One adjacency; ``a < b`` always (INV-M2)."""

    a: int
    b: int
    type: EdgeType
    name: str | None
    multiplier: float | None
    len: float | None


@dataclass(frozen=True)
class MapData:
    """
    The loaded map, immutable for the lifetime of the process.

    Attributes:
        nodes:           ``id -> MapNode``, ascending id order.
        nodes_by_key:    ``key -> MapNode``.
        edges:           ``(min_id, max_id) -> MapEdge``.
        adjacency:       ``id -> tuple[MapEdge, ...]`` sorted by the id of
                         the edge's other end.
        geometry_version: Spec 3.6 version, equals ``geometry.version``.
        manifest_sha256:  normalised SHA-256 of ``manifest.json`` — the
                          future ``ETag`` ingredient of ``/map/manifest``.
        manifest:         the validated ``Manifest`` model, so Issue 4 can
                          build DTOs without re-reading files.
        geometry:         the validated ``Geometry`` model.
        warnings:         non-fatal notes collected during loading
                          (e.g. ids.lock entries with no manifest node).
        retired_ids:      ids in ``ids.lock.json`` with no manifest node —
                          the retired-node set INV-M5 synchronisation
                          removes from ``provinces`` at startup (1.9).
    """

    nodes: Mapping[int, MapNode]
    nodes_by_key: Mapping[str, MapNode]
    edges: Mapping[tuple[int, int], MapEdge]
    adjacency: Mapping[int, tuple[MapEdge, ...]]
    geometry_version: str
    manifest_sha256: str
    manifest: Manifest
    geometry: Geometry
    warnings: tuple[str, ...]
    retired_ids: tuple[int, ...] = ()

    @staticmethod
    def other_end(edge: MapEdge, node_id: int) -> int:
        """The id of ``edge``'s endpoint that is not ``node_id``."""
        return edge.b if edge.a == node_id else edge.a
