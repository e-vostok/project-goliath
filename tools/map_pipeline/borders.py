"""MP-3 (map2_1B): canonical shared borders and coasts -> ``borders.json``.

The method is the Phase A prototype's ``owner`` variant (decision in the
map2_1B TZ): the canonical border line of a land pair ``(a, b)``,
``a < b``, is the contour of the LOWER-id node restricted to the
``borders.eps`` band around the other node. ``geometry.json`` and the
province fills are untouched — this file only *reads* the canonical
paths. The heavy geometry work is reused from
``borders_proto.compute``; this module adds junction snapping, the
perimeter-coverage gate and serialisation.

Junction rule: endpoints of arcs that meet in one junction are snapped
to the meeting centre only when the move stays within
``borders.junction_snap`` — wider openings are water mouths and stay
unbridged. Coverage rule: for every land node, the fraction of its
perimeter lying within ``borders.eps`` of the emitted border and coast
lines must be at least ``1 - borders.coverage_fail``; nodes below
``1 - borders.coverage_warn`` are listed in
``reference/borders_coverage.tsv``. (A length-sum check is impossible
here: the canonical line lies on the lower-id node's contour, whose
arc length legitimately differs from the partner's own ring.)

``borders.json``: ``{"version": <12 hex>, "pairs": {"<a>-<b>": d},
"coasts": {"<id>": d}}`` — one canonical line per ``land`` edge
(including forced ``land_links`` pairs), one coast compound path per
land node (``""`` when fully landlocked). The version is the Spec 3.6
hash over the body plus ``geometry_version``, so the file re-versions
whenever the geometry does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import MultiLineString

from .borders_proto.compute import (
    JUNC_R,
    Arc,
    LandNode,
    junction_groups,
    label_all,
)
from .errors import (
    BORDERS_COVERAGE,
    BORDERS_NO_SEGMENT,
    BORDERS_TOO_LARGE,
    PipelineError,
)
from .graph import KIND_SEA
from .svgpath import borders_version, canonical_json, format_number

COVERAGE_TSV = (
    Path(__file__).resolve().parent / "reference" / "borders_coverage.tsv"
)


@dataclass
class BordersResult:
    """The generated borders document plus report metrics."""

    doc: dict                          # version + pairs + coasts
    text: str                          # canonical JSON, trailing newline
    pair_count: int
    coast_count: int
    coverage_worst: tuple[str, float]  # (key, coverage) of the max |cov-1|
    outliers: list[tuple[str, float]]  # nodes outside coverage_warn
    junction_gap_max: float            # residual gap between meeting lines
    snapped_endpoints: int


def land_nodes_from(graph, canon: dict) -> tuple[dict, list[tuple[int, int]]]:
    """Build ``LandNode`` table + declared ``land`` edge list.

    ``canon`` maps node key -> (Multi)Polygon; the graph supplies ids,
    keys and the edge list. Only ``land`` edges become labelling
    neighbours — straits/coasts never share a drawn border.
    """
    nodes: dict[int, LandNode] = {}
    for gn in graph.nodes:
        if gn.kind == KIND_SEA:
            continue
        nodes[gn.id] = LandNode(gn.id, gn.key, canon[gn.key])
    land_edges = sorted(
        (e.a, e.b) for e in graph.edges if e.type == "land"
    )
    for a, b in land_edges:
        nodes[a].neighbours.append(b)
        nodes[b].neighbours.append(a)
    return nodes, land_edges


# ------------------------------------------------------------- junctions


def _snap_junctions(
    border_arcs: list[Arc],
    coast_arcs: list[Arc],
    snap: float,
    split_r: float,
) -> tuple[int, float]:
    """Snap arc endpoints to their junction centres within ``snap``.

    Returns ``(snapped_count, max_residual_gap)`` — the residual gap is
    the largest remaining distance between endpoints that share a
    junction (wide water mouths deliberately keep theirs).
    """
    items: list[tuple[Arc, int]] = []  # (arc, index into arc.pts)
    endpoints = []
    for arc in (*border_arcs, *coast_arcs):
        if arc.closed or len(arc.pts) < 2 or arc.j0 is None:
            continue
        items.append((arc, 0))
        endpoints.append((len(items) - 1, arc.pts[0], arc.j0))
        items.append((arc, -1))
        endpoints.append((len(items) - 1, arc.pts[-1], arc.j1))

    groups = junction_groups(endpoints, split_r)
    snapped = 0
    for g in groups:
        cx, cy = g["centre"]
        for tag in g["members"]:
            arc, end = items[tag]
            px, py = arc.pts[end]
            if math.hypot(px - cx, py - cy) <= snap and (px, py) != (cx, cy):
                arc.pts[end] = (cx, cy)
                snapped += 1

    gap_max = 0.0
    for g in groups:
        pts = [items[tag][0].pts[items[tag][1]] for tag in g["members"]]
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                gap_max = max(
                    gap_max,
                    math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]),
                )
    return snapped, gap_max


# -------------------------------------------------------------- coverage

COVERAGE_STEP = 0.05  # ring sampling step for the coverage check (units)


def _line_pts(arc: Arc) -> list:
    return arc.pts + ([arc.pts[0]] if arc.closed else [])


def _perimeter_coverage(
    nodes: dict[int, LandNode],
    border_arcs: dict[tuple[int, int], list[Arc]],
    coast_arcs: dict[int, list[Arc]],
    tol: float,
) -> dict[str, float]:
    """Fraction of each node's perimeter within ``tol`` of emitted lines.

    Samples the boundary every ``COVERAGE_STEP`` units and measures it
    against the coast arcs plus the canonical border arcs of every
    declared neighbour — i.e. against exactly what ``borders.json``
    stores for the node's outline.
    """
    out: dict[str, float] = {}
    for nid, node in nodes.items():
        lines = [_line_pts(a) for a in coast_arcs.get(nid, [])]
        for nb in node.neighbours:
            pair = (min(nid, nb), max(nid, nb))
            lines += [_line_pts(a) for a in border_arcs.get(pair, [])]
        lines = [p for p in lines if len(p) >= 2]
        boundary = node.geom.boundary
        if not lines:
            out[node.key] = 1.0 if boundary.is_empty else 0.0
            continue
        mls = MultiLineString(lines)
        rings = (
            list(boundary.geoms)
            if hasattr(boundary, "geoms")
            else [boundary]
        )
        pts = []
        for g in rings:
            n = max(int(g.length / COVERAGE_STEP), 1)
            pts.extend(g.interpolate(np.arange(n) * g.length / n))
        d = shapely.distance(
            shapely.points([(p.x, p.y) for p in pts]), mls
        )
        out[node.key] = float((d <= tol).mean())
    return out


# --------------------------------------------------------- serialisation


def _line_d(pts, closed: bool = False) -> str:
    body = "M " + " ".join(
        f"{format_number(x)} {format_number(y)}" for x, y in pts
    )
    return body + (" Z" if closed else "")


def _dedup_last(pts):
    if len(pts) > 1 and pts[0] == pts[-1]:
        return pts[:-1]
    return pts


def _arc_d(arcs: list[Arc]) -> str:
    return "".join(
        _line_d(_dedup_last(a.pts) if not a.closed else a.pts, a.closed)
        for a in arcs
    )


# ------------------------------------------------------------------ build


def build_borders(
    nodes: dict[int, LandNode],
    land_edges: list[tuple[int, int]],
    geometry_ver: str,
    cfg,
) -> BordersResult:
    """Compute the canonical borders document; raise on invariant breaks.

    Fails with ``BORDERS_NO_SEGMENT`` when a declared ``land`` edge has
    no shared contour, ``BORDERS_COVERAGE`` when a node's borders+coast
    coverage deviates beyond ``borders.coverage_fail`` and
    ``BORDERS_TOO_LARGE`` when the file would exceed
    ``limits.max_borders_bytes``.
    """
    arcs_by_pair, coast_arcs = label_all(nodes, cfg.borders.eps)

    border_arcs: dict[tuple[int, int], list[Arc]] = {}
    for a, b in land_edges:
        sides = arcs_by_pair.get((a, b), {"a": [], "b": []})
        if not sides["a"]:
            raise PipelineError(
                BORDERS_NO_SEGMENT,
                f"land edge ({a}, {b}) {nodes[a].key}-{nodes[b].key} "
                "has no shared contour within borders.eps "
                f"{cfg.borders.eps}",
            )
        border_arcs[(a, b)] = sides["a"]

    snapped, gap_max = _snap_junctions(
        [arc for arcs in border_arcs.values() for arc in arcs],
        [arc for arcs in coast_arcs.values() for arc in arcs],
        cfg.borders.junction_snap,
        JUNC_R,
    )

    coverage = _perimeter_coverage(
        nodes, border_arcs, coast_arcs, cfg.borders.eps
    )
    failed = sorted(
        (k, c) for k, c in coverage.items()
        if c < 1.0 - cfg.borders.coverage_fail
    )
    if failed:
        raise PipelineError(
            BORDERS_COVERAGE,
            f"{len(failed)} node(s) outside the "
            f"+-{cfg.borders.coverage_fail * 100}% perimeter-coverage band",
            [
                f"{k}: coverage {round(c * 100, 2)}%"
                for k, c in failed[:10]
            ],
        )
    outliers = sorted(
        ((k, c) for k, c in coverage.items()
         if c < 1.0 - cfg.borders.coverage_warn),
        key=lambda kc: (kc[1], kc[0]),
    )
    worst = min(coverage.items(), key=lambda kc: kc[1])

    pairs = {
        f"{a}-{b}": _arc_d(arcs) for (a, b), arcs in sorted(border_arcs.items())
    }
    coasts = {
        str(nid): _arc_d(coast_arcs.get(nid, [])) for nid in sorted(nodes)
    }
    version = borders_version(geometry_ver, pairs, coasts)
    doc = {"version": version, "pairs": pairs, "coasts": coasts}
    text = canonical_json(doc) + "\n"
    size = len(text.encode("utf-8"))
    if size > cfg.limits.max_borders_bytes:
        raise PipelineError(
            BORDERS_TOO_LARGE,
            f"borders.json would be {size} bytes, over "
            f"limits.max_borders_bytes {cfg.limits.max_borders_bytes}",
        )
    return BordersResult(
        doc=doc,
        text=text,
        pair_count=len(pairs),
        coast_count=len(coasts),
        coverage_worst=worst,
        outliers=outliers,
        junction_gap_max=gap_max,
        snapped_endpoints=snapped,
    )


def write_coverage_tsv(outliers: list[tuple[str, float]]) -> None:
    """Nodes outside the +-coverage_warn band, worst first."""
    lines = ["key\tcoverage_pct"]
    lines += [f"{k}\t{round(c * 100, 2)}" for k, c in outliers]
    COVERAGE_TSV.write_bytes(
        ("\n".join(lines) + "\n").encode("utf-8")
    )
