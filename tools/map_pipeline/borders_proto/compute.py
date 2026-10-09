"""Core geometry for the Phase-A shared-borders prototype.

Every point of a land node's contour is assigned to exactly one slot:
``('border', other_id)`` for a declared ``land`` neighbour within ``EPS``
of it (nearest neighbour wins inside the overlap band around junctions)
or ``('coast', None)``. Arcs are maximal same-label runs of the ring,
sliced out of the ORIGINAL vertices so node paths stay canonical.

Two candidate canonical lines per pair (a, b), a < b:
- ``owner``  : the arcs of the lower-id node's own contour (method ii)
- ``mid``    : pointwise midline between the a-side arcs and the nearest
               points of the b-side arcs (method i)
A junction pass then clusters arc endpoints and reports the span (the
visible gap/overshoot if lines stop dead) and the spur length if each
endpoint is snapped to the cluster centroid.
"""
from __future__ import annotations

import json
import math
import time
from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.ops import nearest_points, unary_union

from ..svgpath import parse_path

EPS = 0.12        # assignment band half-width (units)
SAMPLE = 0.02     # densify step for labelling (units)
JUNC_R = 0.35     # same-key junction split radius (units)
MID_TOL = 0.012   # Douglas-Peucker tolerance for midline output
PX_PER_UNIT = 40.0

COAST = -1  # label for "not assigned to any neighbour"


# ------------------------------------------------------------------ data


@dataclass
class LandNode:
    id: int
    key: str
    geom: Polygon | MultiPolygon
    neighbours: list[int] = field(default_factory=list)


def load_map(data_dir):
    with open(data_dir / "manifest.json", encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(data_dir / "geometry.json", encoding="utf-8") as fh:
        geometry = json.load(fh)
    nodes: dict[int, LandNode] = {}
    id_by_key = {}
    for rec in manifest["nodes"]:
        id_by_key[rec["key"]] = rec["id"]
        if rec["kind"] != "LAND":
            continue
        parts = parse_path(geometry["paths"][str(rec["id"])])
        geom = parts[0] if len(parts) == 1 else MultiPolygon(parts)
        nodes[rec["id"]] = LandNode(rec["id"], rec["key"], geom)
    land_edges = [
        (e["a"], e["b"], e.get("len") is None)
        for e in manifest["edges"]
        if e["type"] == "land"
    ]
    for a, b, _manual in land_edges:
        nodes[a].neighbours.append(b)
        nodes[b].neighbours.append(a)
    return manifest, geometry, nodes, land_edges


# ---------------------------------------------------------- ring slicing


def _ring_positions(coords):
    """Cumulative arc positions of the closed ring; result[0]=0."""
    n = len(coords)
    c = [0.0] * (n + 1)
    for i in range(n):
        x0, y0 = coords[i]
        x1, y1 = coords[(i + 1) % n]
        c[i + 1] = c[i] + math.hypot(x1 - x0, y1 - y0)
    return c


def _interp(coords, c, pos):
    n = len(coords)
    i = min(bisect_right(c, pos) - 1, n - 1)
    i2 = (i + 1) % n
    seg = c[i + 1] - c[i]
    t = 0.0 if seg <= 0 else (pos - c[i]) / seg
    x0, y0 = coords[i]
    x1, y1 = coords[i2]
    return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)


def slice_ring(coords, s0, s1):
    """Open polyline of the closed ring between positions ``s0`` <= ``s1``.

    ``s1`` may exceed the ring length (wrap); points are rounded to the
    output grid when serialised, not here.
    """
    c = _ring_positions(coords)
    length = c[-1]
    n = len(coords)
    s0 = s0 % length
    wrapped = s1 > length
    s_end = s1 - length if wrapped else s1
    if not wrapped:
        inner = [coords[i] for i in range(n) if s0 < c[i] < s_end]
    else:
        inner = [coords[i] for i in range(n) if c[i] > s0]
        inner += [coords[i] for i in range(n) if c[i] < s_end]
    out = [_interp(coords, c, s0)]
    out.extend(inner)
    out.append(_interp(coords, c, s_end % length))
    # drop consecutive duplicates (interpolated point == vertex)
    dedup = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - dedup[-1][0], p[1] - dedup[-1][1]) > 1e-9:
            dedup.append(p)
    return dedup


# ------------------------------------------------------------ labelling


def _label_ring(ring, nids, ngeoms, eps):
    """Label dense samples of ``ring``; return (labels, positions, L)."""
    dense = ring.segmentize(SAMPLE)
    pts = np.asarray(dense.coords)[:-1]  # drop closing duplicate
    n = len(pts)
    c = [0.0] * (n + 1)
    for i in range(n):
        c[i + 1] = c[i] + math.hypot(
            pts[(i + 1) % n][0] - pts[i][0],
            pts[(i + 1) % n][1] - pts[i][1],
        )
    pos = np.asarray(c[:-1])
    labels = np.full(n, COAST, dtype=np.int64)
    best = np.full(n, np.inf)
    gpts = shapely.points(pts)
    for nid, ng in zip(nids, ngeoms):
        d = shapely.distance(gpts, ng)
        better = (d <= eps) & (d < best - 1e-12)
        labels[better] = nid
        best = np.minimum(best, d)
    return labels, pos, c[-1]


def _ring_arcs(coords, nids, ngeoms, eps):
    """``[(label, polyline, closed, junc_start, junc_end)]`` tiling the ring.

    Labels are neighbour node ids or ``COAST``. ``junc_*`` is the
    frozenset ``{other_label_before, self, label}`` style junction key of
    the transition at that end — the sorted set of contour owners that
    meet there (``COAST`` marks the outer side). A uniformly-labelled
    ring yields one closed arc with ``None`` junctions.
    """
    line = shapely.geometry.LinearRing([*coords, coords[0]])
    if line.length <= 0:
        return []
    labels, pos, length = _label_ring(line, nids, ngeoms, eps)
    n = len(labels)
    boundaries = []  # (position, label_after, label_before)
    for i in range(n):
        j = (i + 1) % n
        if labels[i] == labels[j]:
            continue
        if j == 0:
            t = (pos[i] + length + pos[0]) / 2
            if t >= length:
                t -= length
        else:
            t = (pos[i] + pos[j]) / 2
        boundaries.append((t, int(labels[j]), int(labels[i])))
    if not boundaries:
        return [(int(labels[0]), list(coords), True, None, None)]
    boundaries.sort()
    arcs = []
    nb = len(boundaries)
    for k, (t0, lab, _prev) in enumerate(boundaries):
        t1 = (
            boundaries[k + 1][0]
            if k + 1 < nb
            else boundaries[0][0] + length
        )
        lab_prev = boundaries[k - 1][1]          # label of previous arc
        lab_next = boundaries[(k + 1) % nb][1]   # label of next arc
        arcs.append(
            (
                lab,
                slice_ring(coords, t0, t1),
                False,
                frozenset((lab_prev, lab)),
                frozenset((lab, lab_next)),
            )
        )
    return arcs


@dataclass
class Arc:
    """One polyline piece of a node ring.

    ``j0``/``j1`` are junction keys — frozensets ``{node, prev, next}``
    of the contour owners meeting at each end (``None`` when closed).
    """

    node: int          # owner node id (the contour this arc lies on)
    label: int         # neighbour id or COAST
    pts: list          # [(x, y), ...]
    closed: bool = False
    j0: frozenset | None = None
    j1: frozenset | None = None

    @property
    def length(self):
        return sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(self.pts, self.pts[1:])
        ) + (
            math.hypot(self.pts[0][0] - self.pts[-1][0],
                       self.pts[0][1] - self.pts[-1][1])
            if self.closed else 0.0
        )


def label_all(nodes, eps):
    """Per node: assign every ring; return (arcs_by_pair, coast_arcs).

    ``arcs_by_pair[(a,b)] = {"a": [Arc], "b": [Arc]}`` holds each side's
    contour pieces. ``coast_arcs[node_id] = [Arc]``.
    """
    arcs_by_pair: dict[tuple[int, int], dict[str, list[Arc]]] = {}
    coast_arcs: dict[int, list[Arc]] = {}
    for nid in sorted(nodes):
        node = nodes[nid]
        nids = sorted(node.neighbours)
        ngeoms = [nodes[i].geom for i in nids]
        parts = (
            list(node.geom.geoms)
            if isinstance(node.geom, MultiPolygon)
            else [node.geom]
        )
        for part in parts:
            # Interior rings are enclosed water (lakes): never shared
            # borders — they are coast by definition.
            for hole in part.interiors:
                pts = [tuple(c) for c in hole.coords[:-1]]
                if len(pts) >= 3:
                    coast_arcs.setdefault(nid, []).append(
                        Arc(nid, COAST, pts, True)
                    )
            for ring in [part.exterior]:
                coords = [tuple(c) for c in ring.coords[:-1]]
                if len(coords) < 3:
                    continue
                for lab, pts, closed, j0, j1 in _ring_arcs(
                    coords, nids, ngeoms, eps
                ):
                    if len(pts) < 2 and not closed:
                        continue
                    arc = Arc(nid, lab, pts, closed)
                    if j0 is not None:
                        arc.j0 = frozenset({nid, *j0})
                        arc.j1 = frozenset({nid, *j1})
                    if lab == COAST:
                        coast_arcs.setdefault(nid, []).append(arc)
                    else:
                        pair = (min(nid, lab), max(nid, lab))
                        side = "a" if nid == pair[0] else "b"
                        arcs_by_pair.setdefault(
                            pair, {"a": [], "b": []}
                        )[side].append(arc)
    return arcs_by_pair, coast_arcs


# ------------------------------------------------------------- midlines


def _resample(pts, step):
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        while acc + seg >= step and seg > 0:
            t = (step - acc) / seg
            a = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            out.append(a)
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            acc = 0.0
        acc += seg
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def midline(arc_a: Arc, b_side: list[Arc]) -> list:
    """Midpoint polyline: arc_a samples vs nearest points of arcs_b."""
    target = MultiLineString([a.pts for a in b_side]) if b_side else None
    src = _resample(arc_a.pts, SAMPLE)
    mid = []
    for p in src:
        if target is None:
            mid.append(p)
            continue
        q = nearest_points(Point(p), target)[1]
        mid.append(((p[0] + q.x) / 2, (p[1] + q.y) / 2))
    line = LineString(mid).simplify(MID_TOL, preserve_topology=False)
    if line.is_empty:
        return mid
    return [tuple(c) for c in line.coords]


# ------------------------------------------------------------ junctions


def junction_groups(endpoint_items, split_r=0.35):
    """Group arc endpoints by junction key, split spatially.

    ``endpoint_items``: iterable of ``(tag, point, jkey)``. All endpoints
    sharing one junction key belong to the same physical meeting unless
    they sit more than ``split_r`` apart (the same node triple can meet
    at several disjoint places). Returns a list of dicts with ``key``,
    ``centre``, ``span`` (max distance between member points — the raw
    gap if nothing is snapped) and ``members`` (list of tags).
    """
    by_key: dict[frozenset, list] = {}
    for tag, pt, jkey in endpoint_items:
        by_key.setdefault(jkey, []).append((tag, pt))
    out = []
    for jkey, items in by_key.items():
        pts = np.asarray([p for _t, p in items])
        if len(items) > 1:
            pairs = cKDTree(pts).query_pairs(split_r)
        else:
            pairs = set()
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, j in pairs:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)
        groups: dict[int, list[int]] = {}
        for i in range(len(items)):
            groups.setdefault(find(i), []).append(i)
        for members in groups.values():
            mp = np.asarray([items[i][1] for i in members])
            centre = mp.mean(axis=0)
            span = 0.0
            for i in members:
                for j in members:
                    if i < j:
                        span = max(
                            span,
                            float(np.hypot(*(pts[i] - pts[j]))),
                        )
            out.append(
                {
                    "key": jkey,
                    "centre": (float(centre[0]), float(centre[1])),
                    "span": span,
                    "members": [items[i][0] for i in members],
                    "member_pts": [items[i][1] for i in members],
                }
            )
    return out
