"""map2_18: contour smoothing between per-node simplification and the
sea cut / borders / metrics.

Every land ring is split into open chains at ANCHOR positions:

- arc boundaries — places along the ring where the nearest other land
  node (within ``borders.eps``) changes, i.e. junctions of three or more
  regions and the ends of every shared-border stretch;
- patch anchors — vertices pinned by ``overrides.yaml`` work
  (``transfer``/``split`` lines, ``transfer_part``/``detach``/
  ``seam_repair`` part contacts, ``land_links`` mutual nearest points);
- frame anchors — ring points lying on the viewBox boundary.

Each chain is resampled at ``smooth.step``, filtered with a Gaussian of
``smooth.sigma`` along the arc length (pinned points restored exactly),
then Douglas-Peucker simplified at ``smooth.post_tolerance``.  Parts
smaller than ``smooth.small_part_area`` scale sigma by
``sqrt(area/small_part_area)`` (never below 0.02).

Pair consistency: arcs of one ring labelled to a neighbouring node are
matched with the neighbour's arcs labelled back (junction clustering,
then midpoint proximity).  A matched stretch is smoothed ONCE — the
canonical line is the pointwise midline between the two sides — and both
rings receive the same interior points between their own (unmoved)
endpoints, so the shared border stays identical vertex-for-vertex.

Every chain carries a fallback ladder — ``sigma``, ``sigma/2``,
``sigma/4``, original.  Guard rails (ring validity, part count, area
and displacement per node, per-pair overlap/gap) ESCALATE a failing
chain one level, pair chains always on both sides, so a neck that
folds under the full filter keeps a gentler smoothing instead of the
raw stairs.  A ring whose every chain reached the last level counts as
kept; more than 3 % of such rings is a build failure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy.ndimage import gaussian_filter1d
from shapely import STRtree
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import nearest_points, substring

from .borders_proto.compute import junction_groups, slice_ring
from .errors import GEOMETRY_INVALID, PipelineError
from .pipeline_config_schema import PipelineConfig
from .svg_source import safe_union
from .svgpath import polygons_of

_SAMPLE = 0.02          # densify step for labelling (units)
_SIGMA_FLOOR = 0.02     # minimum effective sigma (small parts)
_REVERT_LIMIT = 0.03    # build fails when more rings than this revert
_NODE_ISLET_AREA = 1.0  # nodes below this get 4x the area-change limit
_OVERLAP_LIMIT = 0.003  # neighbour overlap flag threshold (u^2)
_OVERLAP_DELTA = 0.002  # overlap must not grow by more than this
_GAP_LIMIT = 0.05       # shared-border separation flag threshold
_GAP_DELTA = 0.01       # gap must not grow by more than this
_LEVELS = 3             # sigma, sigma/2, sigma/4; beyond -> original
_MAX_ROUNDS = 16


@dataclass
class _PairChain:
    """Shared smoothed interior for one matched pair of arcs.

    ``levels[i]`` is the canonical polyline at sigma/(2**i); when the
    ladder is exhausted both sides fall back to their own original arc
    polylines.
    """

    levels: list
    level: int = 0
    reason: str = ""

    @property
    def reverted(self) -> bool:
        return self.level >= len(self.levels)


@dataclass
class _Arc:
    """One labelled run of a ring between two anchor positions."""

    ring: "_Ring"
    label: str | None          # other node key or None (coast)
    s0: float
    s1: float                  # ring positions (s1 may exceed length)
    pts: list                  # sliced polyline, ends on the anchors
    j0: frozenset | None = None
    j1: frozenset | None = None
    closed_full: bool = False  # single arc covering the whole ring
    anchors: list = field(default_factory=list)  # solo split positions
    partner: "_Arc | None" = None
    chain: "_PairChain | None" = None
    levels: list = field(default_factory=list)   # solo ladder
    level: int = 0
    reason: str = ""

    @property
    def reverted(self) -> bool:
        return self.level >= len(self.levels)


@dataclass
class _Ring:
    key: str
    part_index: int
    ring_index: int            # 0 exterior, 1.. interior rings
    coords: list               # unclosed vertex list
    part_area: float
    arcs: list = field(default_factory=list)


@dataclass
class SmoothReport:
    """Numbers printed into ``build_report.md`` and to stdout."""

    rings_total: int = 0
    rings_smoothed: int = 0
    rings_partial: int = 0
    rings_kept: int = 0
    kept: list = field(default_factory=list)      # (key, label, reason)
    chains_solo: int = 0
    chains_paired: int = 0
    reverted_pair_chains: int = 0
    pair_arcs_unmatched: int = 0
    escalated: dict = field(default_factory=dict)  # level -> arc count
    max_displacement: float = 0.0
    max_area_change: float = 0.0
    worst_node_disp: str = ""
    worst_node_area: str = ""
    worst_overlap: list = field(default_factory=list)  # (a, b, new, old)
    worst_gap: list = field(default_factory=list)      # (a, b, new, old)


# ------------------------------------------------------------ primitives


def _cumpos_open(pts) -> list:
    """Cumulative arc positions of an OPEN polyline; result[0]=0."""
    c = [0.0] * len(pts)
    for i in range(1, len(pts)):
        c[i] = c[i - 1] + math.hypot(
            pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        )
    return c


def _cumpos_ring(pts) -> list:
    """Cumulative arc positions of a closed ring; result[0]=0."""
    n = len(pts)
    c = [0.0] * (n + 1)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        c[i + 1] = c[i] + math.hypot(x1 - x0, y1 - y0)
    return c


def _resample(pts, step: float) -> list:
    """Uniform resample of an OPEN polyline; ends kept exactly."""
    if len(pts) < 2:
        return [tuple(p) for p in pts]
    out = [tuple(pts[0])]
    acc = 0.0
    a = tuple(pts[0])
    for b in pts[1:]:
        b = tuple(b)
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        while seg > 0 and acc + seg >= step:
            t = (step - acc) / seg
            a = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            out.append(a)
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            acc = 0.0
        acc += seg
        a = b
    if out[-1] != tuple(pts[-1]):
        out.append(tuple(pts[-1]))
    return out


def _resample_ring(pts, step: float) -> list:
    """Uniform resample of an unclosed ring vertex list."""
    return _resample([*pts, pts[0]], step)[:-1]


def _gauss_open(pts, sigma_s: float) -> np.ndarray:
    """Gaussian filter on an open polyline; endpoints restored exactly."""
    arr = np.asarray(pts, dtype=float)
    if len(arr) < 3 or sigma_s <= 0:
        return arr
    out = np.empty_like(arr)
    for d in (0, 1):
        out[:, d] = gaussian_filter1d(arr[:, d], sigma_s, mode="reflect")
    out[0] = arr[0]
    out[-1] = arr[-1]
    return out


def _gauss_closed(pts, sigma_s: float) -> np.ndarray:
    """Circular Gaussian filter on an unclosed ring vertex list."""
    arr = np.asarray(pts, dtype=float)
    if len(arr) < 4 or sigma_s <= 0:
        return arr
    return np.stack(
        [
            gaussian_filter1d(arr[:, d], sigma_s, mode="wrap")
            for d in (0, 1)
        ],
        axis=1,
    )


def _dp(pts, tol: float) -> list:
    """Douglas-Peucker on an open polyline; returns coordinate list."""
    if len(pts) <= 2 or tol <= 0:
        return [tuple(p) for p in pts]
    line = LineString(pts).simplify(tol, preserve_topology=False)
    if line.is_empty or len(line.coords) < 2:
        return [tuple(pts[0]), tuple(pts[-1])]
    return [tuple(c) for c in line.coords]


def _dp_ring(pts, tol: float) -> list:
    """Douglas-Peucker on an unclosed ring vertex list."""
    if len(pts) <= 3 or tol <= 0:
        return [tuple(p) for p in pts]
    line = shapely.geometry.LinearRing([*pts, pts[0]]).simplify(
        tol, preserve_topology=False
    )
    out = [tuple(c) for c in line.coords[:-1]]
    return out if len(out) >= 3 else [tuple(p) for p in pts]


def _slice_open(pts, s0: float, s1: float) -> list:
    """Sub-polyline of an OPEN pts list between arc positions s0 < s1."""
    cum = _cumpos_open(pts)
    n = len(pts)
    inner = [pts[i] for i in range(n) if s0 < cum[i] < s1]

    def at(pos):
        i = min(np.searchsorted(cum, pos, side="right") - 1, n - 2)
        seg = cum[i + 1] - cum[i]
        t = 0.0 if seg <= 0 else (pos - cum[i]) / seg
        return (
            pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
            pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t,
        )

    return [at(s0), *inner, at(s1)]


def _smooth_segments(
    pts, forced_positions, step: float, sigma_s: float, post_tol: float
) -> list:
    """Smooth an OPEN chain; ``forced_positions`` are interior pinned
    split points (arc positions along ``pts``).  Every segment between
    pinned points is resampled, Gaussian-filtered and DP-simplified.
    """
    total = _cumpos_open(pts)[-1]
    cuts = [0.0] + sorted(
        {p for p in forced_positions if 1e-9 < p < total - 1e-9}
    ) + [total]
    out = [tuple(pts[0])]
    for s0, s1 in zip(cuts, cuts[1:]):
        seg = _resample(_slice_open(pts, s0, s1), step)
        seg = _dp(_gauss_open(seg, sigma_s), post_tol)
        out.extend(seg[1:])
    return out


def _midline(arc_a_pts, arc_b_pts, step: float) -> list:
    """Pointwise midline: ``arc_a`` resampled vs nearest of ``arc_b``."""
    target = LineString(arc_b_pts)
    mid = []
    for p in _resample(arc_a_pts, step):
        q = nearest_points(Point(p), target)[1]
        mid.append(((p[0] + q.x) / 2, (p[1] + q.y) / 2))
    return mid


def _arc_midpoint(pts) -> tuple:
    return tuple(LineString(pts).interpolate(0.5, normalized=True).coords[0])


def _snap_ring(pts, grid: float) -> list:
    """Grid-snap + consecutive dedupe of an unclosed ring vertex list —
    the shape the serialised canonical geometry will actually carry."""
    out: list = []
    for x, y in pts:
        p = (round(x / grid) * grid, round(y / grid) * grid)
        if not out or out[-1] != p:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out = out[:-1]
    return out


# ------------------------------------------------------------- labelling


def _label_ring(coords, cand_keys, cand_geoms, eps: float):
    """Nearest other-node label for each dense sample of the ring.

    Returns ``(labels, positions, length)`` — labels are node keys or
    ``None`` (coast).  The nearest candidate wins inside the overlap band
    around junctions; candidates are evaluated in sorted key order for
    determinism.
    """
    line = shapely.geometry.LinearRing([*coords, coords[0]])
    dense = line.segmentize(_SAMPLE)
    pts = np.asarray(dense.coords)[:-1]
    n = len(pts)
    c = [0.0] * (n + 1)
    for i in range(n):
        c[i + 1] = c[i] + math.hypot(
            pts[(i + 1) % n][0] - pts[i][0],
            pts[(i + 1) % n][1] - pts[i][1],
        )
    pos = np.asarray(c[:-1])
    length = c[-1]
    labels: list = [None] * n
    best = np.full(n, np.inf)
    gpts = shapely.points(pts)
    for key, geom in sorted(zip(cand_keys, cand_geoms)):
        d = shapely.distance(gpts, geom)
        better = (d <= eps) & (d < best - 1e-12)
        for i in np.nonzero(better)[0]:
            labels[i] = key
        best = np.minimum(best, d)
    return labels, pos, length


def _ring_arcs(ring: _Ring, labels, pos, length: float) -> None:
    """Tile the ring into labelled arcs split at label transitions.

    Every boundary position is snapped to the nearest ORIGINAL vertex
    of the ring, so an arc end is always a true ring vertex: at a
    junction the three rings share the same vertex coordinate, which
    keeps the vertex pinned and keeps the two sides of a shared border
    ending on identical points (no sliver at the junction).
    """
    coords = ring.coords
    n = len(labels)
    cum = _cumpos_ring(coords)
    vpos = cum[:-1]

    def snap_v(t: float) -> float:
        best_i, best_d = 0, math.inf
        for i, cp in enumerate(vpos):
            d = abs(cp - t)
            d = min(d, length - d)
            if d < best_d:
                best_i, best_d = i, d
        return vpos[best_i]

    boundaries = []
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
        boundaries.append((snap_v(t), labels[j], labels[i]))
    if not boundaries:
        ring.arcs = [
            _Arc(
                ring=ring,
                label=labels[0],
                s0=0.0,
                s1=length,
                pts=list(coords),
                closed_full=True,
            )
        ]
        return
    boundaries.sort(key=lambda b: b[0])
    nb = len(boundaries)
    for k, (t0, lab, _prev) in enumerate(boundaries):
        t1 = (
            boundaries[k + 1][0]
            if k + 1 < nb
            else boundaries[0][0] + length
        )
        lab_prev = boundaries[k - 1][1]
        lab_next = boundaries[(k + 1) % nb][1]
        ring.arcs.append(
            _Arc(
                ring=ring,
                label=lab,
                s0=t0,
                s1=t1,
                pts=slice_ring(coords, t0, t1),
                j0=frozenset((ring.key, lab_prev, lab)),
                j1=frozenset((ring.key, lab, lab_next)),
            )
        )


def _build_rings(geoms: dict, cfg: PipelineConfig) -> list[_Ring]:
    """Enumerate every ring of every node and label its arcs."""
    keys = sorted(geoms)
    geoms_list = [geoms[k] for k in keys]
    tree = STRtree(geoms_list)
    eps = cfg.borders.eps
    rings: list[_Ring] = []
    for key in keys:
        parts = sorted(
            polygons_of(geoms[key]), key=lambda p: (-p.area, p.bounds)
        )
        for pi, part in enumerate(parts):
            for ri, lr in enumerate([part.exterior, *part.interiors]):
                coords = [tuple(c) for c in lr.coords[:-1]]
                if len(coords) < 3:
                    continue
                rings.append(_Ring(key, pi, ri, coords, part.area))
    for ring in rings:
        xs = [p[0] for p in ring.coords]
        ys = [p[1] for p in ring.coords]
        query_box = box(
            min(xs) - eps - 0.05,
            min(ys) - eps - 0.05,
            max(xs) + eps + 0.05,
            max(ys) + eps + 0.05,
        )
        cand_idx = tree.query(query_box, predicate="intersects")
        cand_keys = [
            keys[i] for i in cand_idx if keys[i] != ring.key
        ]
        cand_geoms = [
            geoms_list[i] for i in cand_idx if keys[i] != ring.key
        ]
        labels, pos, length = _label_ring(
            ring.coords, cand_keys, cand_geoms, eps
        )
        _ring_arcs(ring, labels, pos, length)
    return rings


# ------------------------------------------------------------ anchors


def _project_pos(coords, point) -> float:
    """Arc-length position of ``point``'s projection on the ring."""
    line = shapely.geometry.LinearRing([*coords, coords[0]])
    return float(line.project(Point(point)))


def _frame_anchors(coords, view_box) -> list:
    """Ring positions lying on the viewBox boundary."""
    line = shapely.geometry.LinearRing([*coords, coords[0]])
    inter = line.intersection(box(*view_box).boundary)
    pts = []
    for g in shapely.get_parts(inter):
        if g.is_empty:
            continue
        if g.geom_type == "Point":
            pts.append((g.x, g.y))
        elif g.geom_type == "LineString" and len(g.coords) > 0:
            pts.extend((tuple(g.coords[0]), tuple(g.coords[-1])))
        elif g.geom_type == "MultiLineString":
            for gg in g.geoms:
                if len(gg.coords) > 0:
                    pts.extend(
                        (tuple(gg.coords[0]), tuple(gg.coords[-1]))
                    )
    return [_project_pos(coords, p) for p in pts]


def _protected_lines(overrides) -> dict:
    """Patch geometry that pins ring vertices, per node key."""
    lines: dict[str, list] = {}
    for patch in overrides.geometry_patches:
        if patch.transfer is not None:
            t = patch.transfer
            poly = Polygon([p.as_tuple() for p in t.polygon])
            for key in (t.from_key, t.to_key):
                lines.setdefault(key, []).append(poly.boundary)
        if patch.split is not None:
            s = patch.split
            line = LineString([p.as_tuple() for p in s.line])
            for key in (s.key, s.new_key):
                lines.setdefault(key, []).append(line)
    return lines


def _contact_keys(overrides, seam_keys: frozenset) -> set:
    """Keys whose own parts' contacts pin vertices (map2_11 work)."""
    keys = set(seam_keys)
    for patch in overrides.geometry_patches:
        tp = patch.transfer_part
        if tp is not None:
            keys.update((tp.from_key, tp.to_key))
        d = patch.detach
        if d is not None:
            keys.update((d.from_key, d.new_key))
    return keys


def _link_pairs(overrides) -> list:
    return sorted(
        {tuple(sorted((link.a, link.b))) for link in overrides.land_links}
    )


def _patch_anchors(rings, geoms, overrides, seam_keys, view_box, cfg):
    """Fill ``arc.anchors`` with patch/frame split positions (arc-local)."""
    gap = cfg.smooth.anchor_gap
    lines = _protected_lines(overrides)
    contacts = _contact_keys(overrides, seam_keys)

    link_targets: dict[str, list] = {}
    for a, b in _link_pairs(overrides):
        if a in geoms and b in geoms:
            pa, pb = nearest_points(geoms[a], geoms[b])
            link_targets.setdefault(a, []).append((pa.x, pa.y))
            link_targets.setdefault(b, []).append((pb.x, pb.y))

    for ring in rings:
        pts = []
        for line in lines.get(ring.key, []):
            zone = line.buffer(gap)
            pts.extend(
                _project_pos(ring.coords, c)
                for c in ring.coords
                if zone.covers(Point(c))
            )
        if ring.key in contacts:
            for pi, part in enumerate(polygons_of(geoms[ring.key])):
                if pi == ring.part_index:
                    continue
                zone = part.buffer(gap)
                pts.extend(
                    _project_pos(ring.coords, c)
                    for c in ring.coords
                    if zone.covers(Point(c))
                )
        for pt in link_targets.get(ring.key, []):
            zone = Point(pt).buffer(gap)
            pts.extend(
                _project_pos(ring.coords, c)
                for c in ring.coords
                if zone.covers(Point(c))
            )
        if ring.ring_index == 0:
            pts.extend(_frame_anchors(ring.coords, view_box))
        if not pts:
            continue
        positions = sorted({round(p, 9) for p in pts})
        cum = _cumpos_ring(ring.coords)
        length = cum[-1]
        for arc in ring.arcs:
            if arc.closed_full:
                continue
            s0 = arc.s0 % length
            for p in positions:
                q = p % length
                if arc.s1 <= length:
                    inside = s0 < q < arc.s1
                    local = q - s0
                else:
                    inside = q > s0 or q < arc.s1 - length
                    local = (q - s0) if q > s0 else (q + length - s0)
                if inside:
                    arc.anchors.append(local)


# ------------------------------------------------------- pair matching


def _match_pairs(rings: list[_Ring], eps: float) -> dict:
    """Pair arcs labelled to each other; returns the labelled-pair map."""
    labelled: dict[tuple, dict] = {}
    for ring in rings:
        for arc in ring.arcs:
            if arc.label is None or len(arc.pts) < 2:
                continue
            pair = tuple(sorted((ring.key, arc.label)))
            side = "a" if ring.key == pair[0] else "b"
            labelled.setdefault(pair, {"a": [], "b": []})[side].append(arc)

    for pair in sorted(labelled):
        a_arcs = labelled[pair]["a"]
        b_arcs = labelled[pair]["b"]

        # phase 1: identical junction groups at both ends
        items = []
        for side, arcs in (("a", a_arcs), ("b", b_arcs)):
            for i, arc in enumerate(arcs):
                if arc.j0 is None or arc.j1 is None:
                    continue
                items.append(((side, i, 0), arc.pts[0], arc.j0))
                items.append(((side, i, 1), arc.pts[-1], arc.j1))
        group_of: dict = {}
        for g in junction_groups(items):
            for tag in g["members"]:
                group_of[tag] = id(g)
        used_b: set[int] = set()
        for i, arc in enumerate(a_arcs):
            ga = {
                group_of.get(("a", i, 0)),
                group_of.get(("a", i, 1)),
            } - {None}
            if len(ga) < 2:
                continue
            for j, b in enumerate(b_arcs):
                if j in used_b:
                    continue
                gb = {
                    group_of.get(("b", j, 0)),
                    group_of.get(("b", j, 1)),
                } - {None}
                if gb == ga and len(gb) == 2:
                    arc.partner = b
                    b.partner = arc
                    used_b.add(j)
                    break

        # phase 2: greedy midpoint proximity for what is left
        rest_a = [a for a in a_arcs if a.partner is None]
        rest_b = [b for j, b in enumerate(b_arcs) if j not in used_b]
        while rest_a and rest_b:
            best = None
            for ai, a in enumerate(rest_a):
                ma = _arc_midpoint(a.pts)
                for bi, b in enumerate(rest_b):
                    mb = _arc_midpoint(b.pts)
                    d = math.hypot(ma[0] - mb[0], ma[1] - mb[1])
                    if d <= eps and (best is None or d < best[0]):
                        best = (d, ai, bi)
            if best is None:
                break
            a = rest_a.pop(best[1])
            b = rest_b.pop(best[2])
            a.partner = b
            b.partner = a

    return labelled


# ------------------------------------------------------------ proposals


def _sigma_for(part_area: float, cfg: PipelineConfig) -> float:
    sc = cfg.smooth
    if sc.small_part_area <= 0 or part_area >= sc.small_part_area:
        return sc.sigma
    return max(
        _SIGMA_FLOOR, sc.sigma * math.sqrt(part_area / sc.small_part_area)
    )


def _propose(rings: list[_Ring], cfg: PipelineConfig) -> None:
    """Compute the sigma ladder for every arc and the shared chains."""
    sc = cfg.smooth
    # a closed ring can only pair with a closed ring on the other side
    # (enclave borders); anything else is unpaired and smoothed solo.
    for ring in rings:
        for arc in ring.arcs:
            other = arc.partner
            if other is not None and arc.closed_full != other.closed_full:
                arc.partner = None
                other.partner = None

    for ring in rings:
        sigma_u = _sigma_for(ring.part_area, cfg)
        for arc in ring.arcs:
            if arc.partner is not None:
                continue  # shared chains are built below
            arc.levels = []
            for li in range(_LEVELS):
                sigma_s = (sigma_u / (1 << li)) / sc.step
                if arc.closed_full:
                    dense = _resample_ring(arc.pts, sc.step)
                    pts = _dp_ring(
                        [
                            tuple(p)
                            for p in _gauss_closed(dense, sigma_s)
                        ],
                        sc.post_tolerance,
                    )
                else:
                    pts = _smooth_segments(
                        arc.pts, arc.anchors, sc.step, sigma_s,
                        sc.post_tolerance,
                    )
                # degenerate levels fall back to the original chain
                need = 3 if arc.closed_full else 2
                if len(pts) < need or (
                    arc.closed_full
                    and len(_snap_ring(pts, cfg.output.grid)) < 3
                ):
                    pts = list(arc.pts)
                arc.levels.append(pts)

    # shared chains: one canonical ladder per matched arc pair
    done: set[int] = set()
    for ring in rings:
        for arc in ring.arcs:
            if arc.partner is None or id(arc) in done:
                continue
            b = arc.partner
            done.add(id(arc))
            done.add(id(b))
            sa = _sigma_for(arc.ring.part_area, cfg)
            sb = _sigma_for(b.ring.part_area, cfg)
            sigma_u = min(sa, sb)
            levels = []
            if arc.closed_full:
                dense = _resample_ring(arc.pts, sc.step)
                target = LineString([*b.pts, b.pts[0]])
                base_mid = [
                    (
                        (
                            p[0]
                            + nearest_points(Point(p), target)[1].x
                        )
                        / 2,
                        (
                            p[1]
                            + nearest_points(Point(p), target)[1].y
                        )
                        / 2,
                    )
                    for p in dense
                ]
                for li in range(_LEVELS):
                    sigma_s = (sigma_u / (1 << li)) / sc.step
                    shared = _dp_ring(
                        [
                            tuple(p)
                            for p in _gauss_closed(base_mid, sigma_s)
                        ],
                        sc.post_tolerance,
                    )
                    if len(shared) < 3 or len(
                        _snap_ring(shared, cfg.output.grid)
                    ) < 3:
                        shared = list(arc.pts)
                    levels.append(shared)
                chain = _PairChain(levels=levels)
                arc.chain = b.chain = chain
                arc.levels = b.levels = [
                    list(shared) for shared in levels
                ]
                continue
            mid = _midline(arc.pts, b.pts, sc.step)
            for li in range(_LEVELS):
                sigma_s = (sigma_u / (1 << li)) / sc.step
                shared = _dp(_gauss_open(mid, sigma_s), sc.post_tolerance)
                if len(shared) < 2:
                    shared = [
                        tuple(arc.pts[0]), tuple(arc.pts[-1])
                    ]
                levels.append(shared)
            chain = _PairChain(levels=levels)
            arc.chain = chain
            b.chain = chain
            # orient the shared interior to each side's own ends
            for side in (arc, b):
                side.levels = []
                for shared in levels:
                    interior = shared
                    if interior and math.hypot(
                        side.pts[0][0] - interior[0][0],
                        side.pts[0][1] - interior[0][1],
                    ) > math.hypot(
                        side.pts[0][0] - interior[-1][0],
                        side.pts[0][1] - interior[-1][1],
                    ):
                        interior = interior[::-1]
                    side.levels.append(
                        [side.pts[0], *interior, side.pts[-1]]
                    )


# ------------------------------------------------------------ validation


def _arc_pts(arc: _Arc) -> list:
    """The arc's polyline at its current ladder level (or original)."""
    if arc.chain is not None:
        if arc.chain.reverted:
            return arc.pts
        return arc.levels[arc.chain.level]
    if arc.reverted:
        return arc.pts
    return arc.levels[arc.level]


def _step_arc(arc: _Arc, reason: str = "") -> bool:
    """Escalate one arc (shared chain: both sides); True if it moved."""
    if arc.chain is not None:
        if arc.chain.reverted:
            return False
        arc.chain.level += 1
        arc.chain.reason = reason
        return True
    if arc.reverted:
        return False
    arc.level += 1
    arc.reason = reason
    return True


def _affected_keys(arc: _Arc) -> set:
    """Node keys whose geometry changes when ``arc`` steps a level."""
    keys = {arc.ring.key}
    if arc.partner is not None:
        keys.add(arc.partner.ring.key)
    return keys


def _assemble_part(rings: list[_Ring], grid: float) -> Polygon | None:
    """Polygon from the current arc states of one part's rings.

    Coordinates are grid-snapped before validation: the serialised
    canonical geometry is rounded to ``output.grid``, so sub-grid
    folds at chain joins collapse the same way here as in the shipped
    file.
    """
    by_ring = {}
    for ring in rings:
        by_ring[ring.ring_index] = ring
    ext = by_ring.get(0)
    if ext is None:
        return None

    def ring_coords(ring: _Ring):
        if ring.arcs and ring.arcs[0].closed_full:
            raw = list(_arc_pts(ring.arcs[0]))
        else:
            raw = []
            for arc in ring.arcs:
                pts = _arc_pts(arc)
                if raw and pts and raw[-1] == pts[0]:
                    pts = pts[1:]
                raw.extend(pts)
            if len(raw) > 1 and raw[0] == raw[-1]:
                raw = raw[:-1]
        return _snap_ring(raw, grid)

    ext_coords = ring_coords(ext)
    if len(ext_coords) < 3:
        return None
    holes = []
    for ri in sorted(by_ring):
        if ri == 0:
            continue
        hc = ring_coords(by_ring[ri])
        if len(hc) < 3:
            return None
        holes.append(hc)
    poly = Polygon(ext_coords, holes)
    if poly.is_empty:
        return None
    return poly


def _part_valid(prings: list[_Ring], grid: float) -> bool:
    poly = _assemble_part(prings, grid)
    return poly is not None and poly.is_valid


def _bad_rings(rings: list[_Ring], grid: float) -> list[_Ring]:
    """Rings of one part that fail individually (self-intersection or a
    hole collapsing under the snap)."""
    bad = []
    for ring in rings:
        coords = _ring_coords(ring, grid)
        if len(coords) < 3:
            bad.append(ring)
            continue
        lr = shapely.geometry.LinearRing([*coords, coords[0]])
        if not lr.is_simple:
            bad.append(ring)
    return bad


def _ring_coords(ring: _Ring, grid: float) -> list:
    """Snapped ring coordinates at the current arc levels."""
    if ring.arcs and ring.arcs[0].closed_full:
        raw = list(_arc_pts(ring.arcs[0]))
    else:
        raw = []
        for arc in ring.arcs:
            pts = _arc_pts(arc)
            if raw and pts and raw[-1] == pts[0]:
                pts = pts[1:]
            raw.extend(pts)
        if len(raw) > 1 and raw[0] == raw[-1]:
            raw = raw[:-1]
    return _snap_ring(raw, grid)


def _reason_point(geom) -> Point | None:
    """Location of the first validity failure, or None."""
    try:
        reason = shapely.is_valid_reason(geom)
    except Exception:  # pragma: no cover
        return None
    if "[" not in reason:
        return None
    try:
        x, y = reason[reason.index("[") + 1 : reason.index("]")].split()
        return Point(float(x), float(y))
    except (ValueError, IndexError):  # pragma: no cover
        return None


def _unstep_arc(arc: _Arc) -> None:
    """Undo one ladder step (used to reject a trial that did not help)."""
    if arc.chain is not None:
        arc.chain.level -= 1
    else:
        arc.level -= 1


def _signature(geom) -> tuple:
    """(valid, failure point) — a trial step is only kept when the
    signature changes, i.e. the fault moved or went away."""
    if geom is None or not geom.is_valid:
        pt = _reason_point(geom) if geom is not None else None
        return (
            False,
            (round(pt.x, 4), round(pt.y, 4)) if pt is not None else None,
        )
    return (True, None)


def _trial_step(
    rings: list[_Ring], pt: Point, sig_fn, reason: str
) -> set:
    """Step the arc nearest ``pt`` — but only keep a step that changes
    ``sig_fn`` (the fault moved or the shape became valid).  Candidates
    are tried in distance order; if none helps, the nearest arc still
    steps, guaranteeing progress toward full reversion."""
    cands = []
    for ring in rings:
        for arc in ring.arcs:
            if len(arc.pts) < 2:
                continue
            if arc.chain is not None:
                if arc.chain.reverted:
                    continue
            elif arc.reverted:
                continue
            d = LineString(arc.pts).distance(pt)
            cands.append((d, ring.key, ring.ring_index, arc.s0, arc))
    cands.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    if not cands:
        return set()
    sig0 = sig_fn()
    for _d, _k, _ri, _s0, arc in cands:
        _step_arc(arc, reason)
        if sig_fn() != sig0:
            return _affected_keys(arc)
        _unstep_arc(arc)
    _step_arc(cands[0][4], reason)
    return _affected_keys(cands[0][4])


def _node_ok(new_geom, old_geom, cfg: PipelineConfig):
    """Area + displacement guards for one node; (ok, dev, rel)."""
    if new_geom.is_empty or not new_geom.is_valid:
        return False, math.inf, math.inf
    if len(polygons_of(new_geom)) != len(polygons_of(old_geom)):
        return False, math.inf, math.inf
    rel = abs(new_geom.area - old_geom.area) / max(old_geom.area, 1e-9)
    limit = cfg.smooth.max_area_change
    if old_geom.area < _NODE_ISLET_AREA:
        limit *= 4
    if rel > limit:
        return False, math.inf, rel
    dev = _deviation(new_geom, old_geom)
    if dev > cfg.smooth.max_displacement:
        return False, dev, rel
    return True, dev, rel


def _deviation(a, b, step: float = 0.01) -> float:
    from .geometry import deviation

    return deviation(a, b, step=step)


def _validate(
    rings: list[_Ring],
    geoms: dict,
    cfg: PipelineConfig,
    seed_dirty: set | None = None,
) -> dict:
    """Fixpoint escalation under part/node guard rails.

    The structural check (part validity) is cheap and runs over every
    part each round; the deviation/area node guard is expensive and only
    re-runs for nodes whose arcs stepped a level.  Returns
    ``{key: (Multi)Polygon}`` — the accepted smoothed geometry.
    """
    keys = sorted(geoms)
    by_node: dict[str, list] = {
        k: [r for r in rings if r.key == k] for k in keys
    }
    parts_of: dict = {}
    for key in keys:
        parts = sorted(
            polygons_of(geoms[key]), key=lambda p: (-p.area, p.bounds)
        )
        parts_of[key] = [
            (pi, [r for r in by_node[key] if r.part_index == pi])
            for pi in range(len(parts))
        ]

    dirty = set(keys) if seed_dirty is None else set(seed_dirty)
    for _round in range(_MAX_ROUNDS):
        touched: set = set()
        # structural pass: every part must assemble into a valid polygon
        for key in keys:
            for _pi, prings in parts_of[key]:
                # step arcs at the failure point until the part is
                # valid — at most one accepted step per bad ring plus
                # one for a cross-ring fault, per round
                part = _assemble_part(prings, cfg.output.grid)
                if part is not None and part.is_valid:
                    continue
                for r in _bad_rings(prings, cfg.output.grid):
                    def ring_sig(r=r):
                        coords = _ring_coords(r, cfg.output.grid)
                        if len(coords) < 3:
                            return (False, None)
                        return _signature(Polygon(coords))

                    coords = _ring_coords(r, cfg.output.grid)
                    probe = (
                        _reason_point(Polygon(coords))
                        if len(coords) >= 3
                        else None
                    )
                    touched |= _trial_step(
                        [r],
                        probe or Point(coords[0]),
                        ring_sig,
                        "invalid_part",
                    )
                part = _assemble_part(prings, cfg.output.grid)
                if part is not None and part.is_valid:
                    continue
                pt = _reason_point(part) if part is not None else None
                if pt is None and prings:
                    pt = Point(prings[0].coords[0])
                touched |= _trial_step(
                    prings,
                    pt,
                    lambda: _signature(
                        _assemble_part(prings, cfg.output.grid)
                    ),
                    "invalid_part",
                )
        dirty |= touched
        # node guard pass (only nodes that changed)
        passed = set()
        for key in sorted(dirty):
            parts = []
            for _pi, prings in parts_of[key]:
                p = _assemble_part(prings, cfg.output.grid)
                if p is None or not p.is_valid:
                    parts = None
                    break
                parts.append(p)
            if parts is None:
                continue  # the structural pass is still stepping it
            new_geom = (
                parts[0] if len(parts) == 1 else MultiPolygon(parts)
            )
            ok, _dev, _rel = _node_ok(new_geom, geoms[key], cfg)
            if ok:
                passed.add(key)
                continue
            reason = (
                "area"
                if _rel > cfg.smooth.max_area_change * (
                    4
                    if geoms[key].area < _NODE_ISLET_AREA
                    else 1
                )
                else "displacement"
            )
            for r in by_node[key]:
                for a in r.arcs:
                    if _step_arc(a, reason):
                        touched |= _affected_keys(a)
        dirty = (dirty - passed) | touched
        if not touched:
            break

    return _rebuild(rings, geoms, cfg)


def _rebuild(rings: list[_Ring], geoms: dict, cfg) -> dict:
    """Assemble the geometry map from the current arc levels; any part
    that still fails falls back to its unsmoothed polygon."""
    by_node: dict[str, list] = {}
    for ring in rings:
        by_node.setdefault(ring.key, []).append(ring)
    out: dict = {}
    for key in sorted(geoms):
        parts = []
        for pi in sorted(
            {r.part_index for r in by_node.get(key, [])}
        ):
            prings = [
                r for r in by_node[key] if r.part_index == pi
            ]
            p = _assemble_part(prings, cfg.output.grid)
            if p is None or not p.is_valid:  # pragma: no cover
                p = Polygon(
                    prings[0].coords,
                    [r.coords for r in prings if r.ring_index],
                )
            parts.append(p)
        if not parts:
            out[key] = geoms[key]
            continue
        out[key] = parts[0] if len(parts) == 1 else MultiPolygon(parts)
    return out


def _polish(
    rings: list[_Ring], geoms: dict, cfg: PipelineConfig
) -> dict:
    """Give fully-reverted rings a second chance: tentatively un-step
    each arc one level (toward σ/4 smoothing) and keep it only where
    every affected part stays valid and every affected node keeps its
    area/displacement guards."""
    by_node: dict[str, list] = {}
    for ring in rings:
        by_node.setdefault(ring.key, []).append(ring)
    parts_of: dict = {
        key: [
            [r for r in rs if r.part_index == pi]
            for pi in sorted({r.part_index for r in rs})
        ]
        for key, rs in by_node.items()
    }

    def node_geom(key) -> object:
        parts = []
        for prings in parts_of.get(key, []):
            p = _assemble_part(prings, cfg.output.grid)
            if p is None or not p.is_valid:
                return None
            parts.append(p)
        return parts[0] if len(parts) == 1 else MultiPolygon(parts)

    def trial_ok(arc) -> bool:
        for key in _affected_keys(arc):
            g = node_geom(key)
            if g is None:
                return False
            ok, _d, _r = _node_ok(g, geoms[key], cfg)
            if not ok:
                return False
        return True

    for _sweep in range(3):
        freed = False
        for ring in sorted(
            rings, key=lambda r: (r.key, r.part_index, r.ring_index)
        ):
            states = [
                a.chain.reverted if a.chain is not None else a.reverted
                for a in ring.arcs
            ]
            if not all(states):
                continue
            for arc in ring.arcs:
                if arc.chain is not None:
                    arc.chain.level -= 1
                else:
                    arc.level -= 1
                if trial_ok(arc):
                    freed = True
                    break
                # rejected: put the level back toward reversion
                if arc.chain is not None:
                    arc.chain.level += 1
                else:
                    arc.level += 1
        if not freed:
            break
    return _rebuild(rings, geoms, cfg)


# --------------------------------------------------------- pair guards


def _pair_guards(
    out: dict,
    rings: list[_Ring],
    labelled: dict,
    geoms: dict,
    cfg: PipelineConfig,
) -> tuple[dict, list]:
    """Measure shared-border gap/overlap; step bad shared stretches.

    ``gap`` is the max separation between the two sides along the
    stretch where they run together — one side's arc labelled to the
    neighbour vs the neighbour's arcs labelled back — with a
    ``borders.junction_snap`` margin at every arc end (the snapped line
    joins cover junction fan-out, which existed before smoothing).

    The guards are delta-based: the source map carries sliver overlaps
    and junction fan-outs on most pairs, so a pair only fails when
    smoothing makes it measurably worse — overlap above
    ``_OVERLAP_LIMIT`` AND ``_OVERLAP_DELTA`` over its pre-smoothing
    value, or gap above ``_GAP_LIMIT`` AND ``_GAP_DELTA`` over its
    pre-smoothing value.  A failing pair first steps its unmatched
    (solo) arcs; if it still fails, the shared chains step too.
    Returns ``(geoms, rows)`` where a row is
    ``(a, b, overlap, gap, overlap_old, gap_old)``.
    """
    margin = cfg.borders.junction_snap

    # pair -> {'a': [Arc], 'b': [Arc]} of labelled arcs
    pair_arcs: dict = {}
    for ring in rings:
        for arc in ring.arcs:
            if arc.label is None or len(arc.pts) < 2:
                continue
            pair = tuple(sorted((ring.key, arc.label)))
            side = "a" if ring.key == pair[0] else "b"
            pair_arcs.setdefault(pair, {"a": [], "b": []})[side].append(
                arc
            )

    def gap_side(arcs_a, arcs_b, other_boundary, use_new) -> float:
        target = (
            shapely.MultiLineString(
                [
                    (_arc_pts(a) if use_new else a.pts)
                    for a in arcs_b
                    if len(a.pts) > 1
                ]
            )
            if arcs_b
            else other_boundary
        )
        worst = 0.0
        for arc in arcs_a:
            pts = _arc_pts(arc) if use_new else arc.pts
            if len(pts) < 2:
                continue
            line = LineString(pts)
            if line.length <= 2 * margin:
                continue
            inner = substring(line, margin, line.length - margin)
            n = max(int(inner.length / _SAMPLE), 1)
            samples = [
                inner.interpolate(t)
                for t in np.linspace(0, inner.length, n + 1)
            ]
            d = shapely.distance(
                shapely.points([(p.x, p.y) for p in samples]), target
            )
            worst = max(worst, float(d.max()))
        return worst

    def pair_gap(pair, geom_by_key, use_new) -> float:
        a, b = pair
        sides = pair_arcs.get(pair, {"a": [], "b": []})
        return max(
            gap_side(
                sides["a"], sides["b"], geom_by_key[b].boundary, use_new
            ),
            gap_side(
                sides["b"], sides["a"], geom_by_key[a].boundary, use_new
            ),
        )

    # baseline: same metrics on the unsmoothed geometry
    old: dict = {}
    for pair in sorted(labelled):
        a, b = pair
        old[pair] = (
            float(geoms[a].intersection(geoms[b]).area),
            pair_gap(pair, geoms, False),
        )

    def measure(geom_by_key):
        rows = []
        for pair in sorted(labelled):
            a, b = pair
            overlap = float(
                geom_by_key[a].intersection(geom_by_key[b]).area
            )
            gap = pair_gap(pair, geom_by_key, True)
            rows.append((a, b, overlap, gap, *old[pair]))
        return rows

    for _round in range(6):
        rows = measure(out)
        offenders = [
            (a, b)
            for a, b, ov, gp, ov0, gp0 in rows
            if (ov > _OVERLAP_LIMIT and ov > ov0 + _OVERLAP_DELTA)
            or (gp > _GAP_LIMIT and gp > gp0 + _GAP_DELTA)
        ]
        if not offenders:
            break
        seed: set = set()
        for pair in offenders:
            arcs = [x for s in pair_arcs[pair].values() for x in s]
            solo = [
                a for a in arcs if a.chain is None and not a.reverted
            ]
            targets = (
                solo
                if solo
                else [
                    a
                    for a in arcs
                    if a.chain is not None and not a.chain.reverted
                ]
            )
            for arc in targets:
                if _step_arc(arc, "pair_seam"):
                    seed |= _affected_keys(arc)
        if not seed:
            break
        out = _validate(rings, geoms, cfg, seed)
    return out, measure(out)


# ------------------------------------------------------------ reporting


def _stats(out: dict, geoms: dict, rings: list[_Ring], cfg) -> SmoothReport:
    rep = SmoothReport()
    rep.rings_total = len(rings)
    for ring in rings:
        states = [
            (a.chain.reverted if a.chain is not None else a.reverted)
            for a in ring.arcs
        ]
        if all(states):
            rep.rings_kept += 1
        elif any(states):
            rep.rings_partial += 1
        else:
            rep.rings_smoothed += 1
    for ring in rings:
        for a in ring.arcs:
            if a.chain is not None and a.chain.reverted:
                rep.kept.append(
                    (ring.key, a.label or "coast", a.chain.reason)
                )
            elif a.chain is None and a.reverted:
                rep.kept.append((ring.key, a.label or "coast", a.reason))
    rep.chains_solo = sum(
        1 for r in rings for a in r.arcs if a.chain is None
    )
    rep.chains_paired = sum(
        1
        for r in rings
        for a in r.arcs
        if a.chain is not None and a.ring.key <= a.partner.ring.key
    )
    rep.pair_arcs_unmatched = sum(
        1
        for r in rings
        for a in r.arcs
        if a.label is not None and a.chain is None
    )
    chains = {
        id(a.chain): a.chain
        for r in rings
        for a in r.arcs
        if a.chain is not None
    }
    rep.reverted_pair_chains = sum(
        1 for c in chains.values() if c.reverted
    )
    for r in rings:
        for a in r.arcs:
            lev = a.chain.level if a.chain is not None else a.level
            rep.escalated[lev] = rep.escalated.get(lev, 0) + 1
    for key in sorted(out):
        old, new = geoms[key], out[key]
        dev = _deviation(new, old)
        rel = abs(new.area - old.area) / max(old.area, 1e-9)
        if dev > rep.max_displacement:
            rep.max_displacement = dev
            rep.worst_node_disp = key
        if rel > rep.max_area_change:
            rep.max_area_change = rel
            rep.worst_node_area = key
    return rep


# ---------------------------------------------------------------- entry


def smooth_land_geometries(
    geoms: dict,
    overrides,
    seam_keys: frozenset,
    view_box: tuple,
    cfg: PipelineConfig,
) -> tuple[dict, SmoothReport]:
    """Smooth every ring of ``geoms``; return (new_geoms, report).

    ``geoms`` maps node key -> (Multi)Polygon (post-simplification).
    Everything downstream (land mask, sea cut, canon serialisation,
    metrics, borders, manifest) is recomputed from the returned
    geometry.
    """
    if not geoms:
        return geoms, SmoothReport()
    rings = _build_rings(geoms, cfg)
    _patch_anchors(rings, geoms, overrides, seam_keys, view_box, cfg)
    labelled = _match_pairs(rings, cfg.borders.eps)
    _propose(rings, cfg)
    out = _validate(rings, geoms, cfg)
    out, _rows = _pair_guards(out, rings, labelled, geoms, cfg)
    out = _polish(rings, geoms, cfg)
    out, rows = _pair_guards(out, rings, labelled, geoms, cfg)

    rep = _stats(out, geoms, rings, cfg)
    rep.worst_overlap = sorted(
        ((a, b, ov, ov0) for a, b, ov, _g, ov0, _g0 in rows),
        key=lambda r: (-r[2], r[0], r[1]),
    )[:5]
    rep.worst_gap = sorted(
        ((a, b, g, g0) for a, b, _o, g, _o0, g0 in rows),
        key=lambda r: (-r[2], r[0], r[1]),
    )[:5]
    if rep.rings_kept > _REVERT_LIMIT * rep.rings_total:
        raise PipelineError(
            GEOMETRY_INVALID,
            f"smooth: {rep.rings_kept} of {rep.rings_total} rings kept "
            f"their unsmoothed shape (> {_REVERT_LIMIT * 100}%) — "
            "guard rails reject the smoothing at these parameters",
            [f"{k}: {lab} ({why})" for k, lab, why in rep.kept[:20]],
        )
    return out, rep


def smooth_geometry_solo(geom, cfg: PipelineConfig):
    """Closed-ring Gaussian smoothing of a standalone (multi)polygon.

    Used for the excluded-land union inside ``build_land_mask`` — the
    smoothed contour feeds the sea cut, so coasts against excluded land
    lose their stairs too.  On any structural failure the original part
    is kept.
    """
    sc = cfg.smooth
    parts = []
    for part in polygons_of(geom):
        rings = []
        ok = True
        for lr in (part.exterior, *part.interiors):
            coords = [tuple(c) for c in lr.coords[:-1]]
            if len(coords) < 4:
                rings.append(coords)
                continue
            best = None
            for li in range(_LEVELS):
                sigma_s = (
                    _sigma_for(part.area, cfg) / (1 << li)
                ) / sc.step
                dense = _resample_ring(coords, sc.step)
                cand = _dp_ring(
                    [tuple(p) for p in _gauss_closed(dense, sigma_s)],
                    sc.post_tolerance,
                )
                cand = _snap_ring(cand, cfg.output.grid)
                if len(cand) < 3:
                    continue
                best = cand
                break
            if best is None:
                best = coords
            rings.append(best)
        cand = Polygon(rings[0], rings[1:])
        if cand.is_empty or not cand.is_valid:
            parts.append(part)
            continue
        if _deviation(part, cand, step=0.02) > sc.max_displacement:
            parts.append(part)
            continue
        parts.append(cand)
    union = safe_union(parts)
    polys = polygons_of(union)
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)
