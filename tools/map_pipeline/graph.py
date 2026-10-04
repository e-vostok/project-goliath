"""Appendix A step 6 (Spec 3.1): edges between nodes, manual overrides,
straits, and the graph invariants INV-M2 / INV-M3.

Automatic edges come first — ``land`` pairs by the shared-boundary formula
on the vector geometries, ``coast`` and ``sea`` pairs by pixel contact on
the raster — then ``edges_remove``, ``edges_add`` and ``straits`` are
applied in that order. Every independent defect is collected and reported
together.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely import STRtree
from shapely.geometry import Polygon

from .errors import (
    EDGE_REMOVE_NOT_FOUND,
    EDGE_TYPE_MISMATCH,
    EDGE_UNKNOWN_NODE,
    GRAPH_DISCONNECTED,
    GRAPH_INVARIANT,
    STRAIT_ALREADY_CONNECTED,
    PipelineError,
    PipelineFailure,
)
from .models import Overrides
from .pipeline_config_schema import PipelineConfig
from .seas import SeaRaster
from .svg_source import safe_union

KIND_LAND = "LAND"
KIND_SEA = "SEA"

# INV-M2: the kinds an edge type may join (sorted pair).
_TYPE_ENDS = {
    "land": ("LAND", "LAND"),
    "coast": ("LAND", "SEA"),
    "sea": ("SEA", "SEA"),
    "strait": ("LAND", "LAND"),
}


@dataclass
class GraphNode:
    id: int
    key: str
    kind: str  # KIND_LAND | KIND_SEA
    name: str | None
    name_ru: str | None
    area: float
    geom: object | None = None  # land only: union of parts
    zone_index: int = 0  # sea only: 1..N


@dataclass
class Edge:
    a: int
    b: int
    type: str
    len: float | None  # contact/border length in units; None = manual
    name: str | None = None
    multiplier: float | None = None
    manual: bool = False  # added via edges_add, did not exist before


@dataclass
class Graph:
    nodes: list[GraphNode]  # sorted by id
    edges: list[Edge]  # sorted by (a, b)
    info: list[str] = field(default_factory=list)
    connected_no_manual: bool = True


def _node_union(node) -> object:
    """Union of a land node's parts; holes of the parts are ignored."""
    return safe_union(
        [Polygon(p.exterior) if p.interiors else p for p in node.parts]
    )


def _land_edges(
    land_nodes: list[GraphNode], eps: float, l_min: float
) -> dict[tuple[int, int], Edge]:
    """LAND-LAND pairs by the shared-boundary formula of Spec 3.1."""
    geoms = [n.geom for n in land_nodes]
    buffered = [g.buffer(eps) for g in geoms]
    tree = STRtree(geoms)
    edges: dict[tuple[int, int], Edge] = {}
    for i, node in enumerate(land_nodes):
        for j in tree.query(geoms[i], predicate="dwithin", distance=eps):
            if j <= i:
                continue
            other = land_nodes[j]
            lab = geoms[i].boundary.intersection(buffered[j]).length
            lba = geoms[j].boundary.intersection(buffered[i]).length
            length = max(lab, lba)
            if length < l_min:
                continue
            a, b = sorted((node.id, other.id))
            edges[(a, b)] = Edge(a=a, b=b, type="land", len=length)
    return edges


def _contact_pairs(
    zone_labels: np.ndarray, land_labels: np.ndarray
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """Count 4-connected pixel contacts between zones and land / zones.

    Only right and down neighbours are examined, so each unordered pixel
    pair is counted once. Returns ``{(zone_idx, land_idx): count}`` and
    ``{(zone_idx_a, zone_idx_b): count}``.
    """
    coast: dict[tuple[int, int], int] = {}
    sea: dict[tuple[int, int], int] = {}
    for za, zb, la, lb in (
        (zone_labels[:, :-1], zone_labels[:, 1:],
         land_labels[:, :-1], land_labels[:, 1:]),
        (zone_labels[:-1, :], zone_labels[1:, :],
         land_labels[:-1, :], land_labels[1:, :]),
    ):
        chunks = []
        m = (za > 0) & (lb > 0)
        if m.any():
            chunks.append(np.column_stack([za[m], lb[m]]))
        m = (la > 0) & (zb > 0)
        if m.any():
            chunks.append(np.column_stack([zb[m], la[m]]))
        if chunks:
            uniq, cnt = np.unique(
                np.vstack(chunks), axis=0, return_counts=True
            )
            for (zi, li), c in zip(uniq.tolist(), cnt.tolist()):
                key = (int(zi), int(li))
                coast[key] = coast.get(key, 0) + c
        m = (za > 0) & (zb > 0) & (za != zb)
        if m.any():
            lo = np.minimum(za[m], zb[m])
            hi = np.maximum(za[m], zb[m])
            uniq, cnt = np.unique(
                np.column_stack([lo, hi]), axis=0, return_counts=True
            )
            for (z1, z2), c in zip(uniq.tolist(), cnt.tolist()):
                key = (int(z1), int(z2))
                sea[key] = sea.get(key, 0) + c
    return coast, sea


def _contact_edges(
    sea: SeaRaster,
    land_labels: np.ndarray,
    land_nodes: list[GraphNode],
    sea_nodes: dict[int, GraphNode],
    cfg: PipelineConfig,
) -> dict[tuple[int, int], Edge]:
    """LAND-SEA (coast) and SEA-SEA (sea) pairs from pixel contacts.

    ``sea_nodes`` maps zone index -> node; retired zones have no entry, so
    their pixels never produce an edge.
    """
    r = sea.frame.r
    l_min = cfg.geometry.min_border_length
    coast, sea_pairs = _contact_pairs(sea.labels, land_labels)
    edges: dict[tuple[int, int], Edge] = {}
    for (zi, li), count in sorted(coast.items()):
        if zi not in sea_nodes:
            continue
        length = count / r
        if length < l_min:
            continue
        a, b = sorted(
            (sea_nodes[zi].id, land_nodes[li - 1].id)
        )
        edges[(a, b)] = Edge(a=a, b=b, type="coast", len=length)
    for (z1, z2), count in sorted(sea_pairs.items()):
        if z1 not in sea_nodes or z2 not in sea_nodes:
            continue
        length = count / r
        if length < l_min:
            continue
        a, b = sorted((sea_nodes[z1].id, sea_nodes[z2].id))
        edges[(a, b)] = Edge(a=a, b=b, type="sea", len=length)
    return edges


def _kinds_ok(edge_type: str, a: GraphNode, b: GraphNode) -> bool:
    return tuple(sorted((a.kind, b.kind))) == _TYPE_ENDS[edge_type]


def _apply_overrides(
    edges: dict[tuple[int, int], Edge],
    by_key: dict[str, GraphNode],
    overrides: Overrides,
) -> tuple[list[str], list[PipelineError]]:
    """Apply edges_remove, then edges_add, then straits — in that order."""
    info: list[str] = []
    errors: list[PipelineError] = []

    for i, e in enumerate(overrides.edges_remove):
        na, nb = by_key.get(e.a), by_key.get(e.b)
        if na is None or nb is None:
            unknown = e.a if na is None else e.b
            errors.append(
                PipelineError(
                    EDGE_UNKNOWN_NODE,
                    f"edges_remove[{i}]: unknown node key {unknown!r}",
                )
            )
            continue
        pair = (min(na.id, nb.id), max(na.id, nb.id))
        if pair not in edges:
            errors.append(
                PipelineError(
                    EDGE_REMOVE_NOT_FOUND,
                    f"edges_remove[{i}]: no edge between {e.a!r} and {e.b!r}",
                )
            )
            continue
        del edges[pair]

    for i, e in enumerate(overrides.edges_add):
        na, nb = by_key.get(e.a), by_key.get(e.b)
        if na is None or nb is None:
            unknown = e.a if na is None else e.b
            errors.append(
                PipelineError(
                    EDGE_UNKNOWN_NODE,
                    f"edges_add[{i}]: unknown node key {unknown!r}",
                )
            )
            continue
        if not _kinds_ok(e.type, na, nb):
            errors.append(
                PipelineError(
                    EDGE_TYPE_MISMATCH,
                    f"edges_add[{i}]: type {e.type!r} cannot join "
                    f"{na.kind} {e.a!r} and {nb.kind} {e.b!r}",
                )
            )
            continue
        pair = (min(na.id, nb.id), max(na.id, nb.id))
        if pair in edges:
            info.append(
                f"edges_add {e.a}-{e.b} ({e.type}): edge already present; "
                "kept as one"
            )
            continue
        edges[pair] = Edge(
            a=pair[0], b=pair[1], type=e.type, len=None, manual=True
        )

    for i, s in enumerate(overrides.straits):
        na, nb = by_key.get(s.a), by_key.get(s.b)
        if na is None or nb is None:
            unknown = s.a if na is None else s.b
            errors.append(
                PipelineError(
                    EDGE_UNKNOWN_NODE,
                    f"straits[{i}]: unknown node key {unknown!r}",
                )
            )
            continue
        if na.kind != KIND_LAND or nb.kind != KIND_LAND:
            errors.append(
                PipelineError(
                    EDGE_TYPE_MISMATCH,
                    f"straits[{i}]: strait endpoints must be LAND, got "
                    f"{na.kind} {s.a!r} and {nb.kind} {s.b!r}",
                )
            )
            continue
        pair = (min(na.id, nb.id), max(na.id, nb.id))
        if pair in edges:
            errors.append(
                PipelineError(
                    STRAIT_ALREADY_CONNECTED,
                    f"straits[{i}]: {s.a!r} and {s.b!r} already share a "
                    f"{edges[pair].type} edge",
                )
            )
            continue
        edges[pair] = Edge(
            a=pair[0],
            b=pair[1],
            type="strait",
            len=None,
            name=s.name,
            multiplier=s.multiplier,
        )
    return info, errors


def _components(node_ids: list[int],
                edges: dict[tuple[int, int], Edge]) -> list[list[int]]:
    parent = {i: i for i in node_ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    groups: dict[int, list[int]] = {}
    for i in node_ids:
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def _check_invariants(
    graph_nodes: list[GraphNode], edges: dict[tuple[int, int], Edge]
) -> bool:
    """INV-M2 then INV-M3; raises PipelineFailure, returns connectivity of
    the graph minus straits and manual edges (for the report)."""
    by_id = {n.id: n for n in graph_nodes}
    errors: list[PipelineError] = []
    for (a, b), e in edges.items():
        problems = []
        if a == b:
            problems.append("self loop")
        if not (e.a < e.b) or (e.a, e.b) != (a, b):
            problems.append("pair is not stored as a < b")
        na, nb = by_id.get(a), by_id.get(b)
        if na is None or nb is None:
            problems.append("endpoint does not exist")
        elif not _kinds_ok(e.type, na, nb):
            problems.append(
                f"type {e.type!r} joins {na.kind} and {nb.kind}"
            )
        if problems:
            errors.append(
                PipelineError(
                    GRAPH_INVARIANT,
                    f"INV-M2 violation on pair ({a}, {b}): "
                    + "; ".join(problems),
                )
            )
    if errors:
        raise PipelineFailure(errors)

    node_ids = sorted(by_id)
    groups = _components(node_ids, edges)
    if len(groups) > 1:
        details = []
        for group in groups[1:]:
            members = ", ".join(
                f"{by_id[i].key} (area {round(by_id[i].area, 2)})"
                for i in sorted(group)
            )
            details.append(f"component of {len(group)}: {members}")
        raise PipelineFailure(
            [
                PipelineError(
                    GRAPH_DISCONNECTED,
                    f"INV-M3 violation: graph has {len(groups)} components; "
                    "all but the largest:",
                    details,
                )
            ]
        )

    real = {
        pair: e
        for pair, e in edges.items()
        if e.type != "strait" and not e.manual
    }
    return len(_components(node_ids, real)) == 1


def build_graph(
    land: dict,  # key -> _Node (pipeline)
    sea: SeaRaster,
    ids: dict[str, int],
    overrides: Overrides,
    cfg: PipelineConfig,
    land_labels: np.ndarray,
) -> Graph:
    """Build the full node graph; raises ``PipelineFailure`` on defects."""
    ordered_keys = sorted(land, key=lambda k: ids[k])
    land_nodes = [
        GraphNode(
            id=ids[key],
            key=key,
            kind=KIND_LAND,
            name=land[key].source_name.replace("_", " "),
            name_ru=overrides.names_ru.get(key) or None,
            area=sum(p.area for p in land[key].parts),
            geom=_node_union(land[key]),
            zone_index=0,
        )
        for key in ordered_keys
    ]
    # 1.9: retired zones are absent from the node table — their pixels keep
    # their labels but produce no node and no edges.
    sea_nodes = {
        z + 1: GraphNode(
            id=ids[key],
            key=key,
            kind=KIND_SEA,
            name=None,
            name_ru=sea.zone_name_ru[z],
            area=sea.zone_areas[z],
            zone_index=z + 1,
        )
        for z, key in enumerate(sea.zone_keys)
        if key not in sea.retired
    }

    by_key = {n.key: n for n in land_nodes + list(sea_nodes.values())}
    edges = _land_edges(
        land_nodes, cfg.geometry.border_epsilon, cfg.geometry.min_border_length
    )
    edges.update(
        _contact_edges(sea, land_labels, land_nodes, sea_nodes, cfg)
    )
    info, errors = _apply_overrides(edges, by_key, overrides)
    if errors:
        raise PipelineFailure(errors)

    graph_nodes = sorted(
        land_nodes + list(sea_nodes.values()), key=lambda n: n.id
    )
    connected_no_manual = _check_invariants(graph_nodes, edges)
    return Graph(
        nodes=graph_nodes,
        edges=[edges[p] for p in sorted(edges)],
        info=info,
        connected_no_manual=connected_no_manual,
    )
