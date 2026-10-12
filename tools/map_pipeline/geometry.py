"""Appendix A steps 7–9: final node geometries, anchors/bboxes/areas and
the ``outside`` contour with lake windows.

Land provinces are simplified per node (Spec 1.4: neighbouring source
borders do not coincide, so shared borders are not preserved on land —
the client covers the seams with the province outline). Sea zones come
from the MP-2 label raster grown a few pixels into land, vectorised as an
exact pixel coverage, simplified as one coverage and cut by the land mask.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from scipy import ndimage
from shapely import (
    coverage_is_valid,
    coverage_simplify,
    make_valid,
    maximum_inscribed_circle,
    points as _points,
    set_precision,
)
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import polygonize, polylabel, unary_union

from .errors import (
    GEOMETRY_EMPTY,
    GEOMETRY_INVALID,
    PipelineError,
    PipelineFailure,
)
from .pipeline_config_schema import PipelineConfig
from .seas import (
    KIND_BAY,
    KIND_LAKE,
    KIND_LAND,
    SeaRaster,
    mask_from_geometry,
)
from .svgpath import dumps, parse_path, polygons_of
from .svg_source import safe_union

# ``outside`` parts smaller than this are the "small isolated fragments"
# the build report counts (Spec 1.5 §3.4).
_FRAGMENT_MAX_AREA = 5.0


@dataclass
class NodeMetrics:
    """Per-node ``anchor``, ``bbox``, ``area`` and ``label`` for the manifest."""

    anchor: tuple[float, float]
    bbox: tuple[float, float, float, float]
    area: float
    # map2_6: label box ``(x, y, w, h)`` — anchor plus free width/height
    # the client fits the node name into.
    label: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    # map2_20: spine baseline the curved name is laid out along.
    spine: "NodeSpine | None" = None


@dataclass
class SeaBuild:
    """Intermediate numbers reported by the sea vectorisation."""

    geoms: dict[str, Polygon | MultiPolygon] = field(default_factory=dict)
    face_count: int = 0
    labelled_faces: int = 0
    vertices_before_cut: int = 0
    vertices_after_cut: int = 0
    area_before_cut: float = 0.0
    area_after_cut: float = 0.0
    fill_merged: int = 0
    fill_merged_area: float = 0.0
    fill_leftover: int = 0
    fill_leftover_area: float = 0.0


@dataclass
class OutsideBuild:
    """``outside`` geometry plus the lake-region statistics."""

    outside: Polygon | MultiPolygon
    nodes_union: Polygon | MultiPolygon
    lake_region: Polygon | MultiPolygon | None
    lake_pieces: int = 0
    lake_area: float = 0.0
    lake_spill: float = 0.0
    lake_windows: int = 0
    lake_holes: int = 0
    holes_dropped: int = 0
    lakes_dropped: int = 0
    lakes_dropped_area: float = 0.0
    lake_rims: int = 0
    lake_rims_area: float = 0.0


def _polygon_list(geom) -> list[Polygon]:
    return polygons_of(geom)


def _snap_pointwise(geom, grid: float) -> list:
    """Grid snap that never folds or deletes thin features.

    ``set_precision``'s default ``valid_output`` cleanup removes the
    sub-grid notches and needles the MapChart source is full of, which can
    shift the boundary by far more than the grid step. Pointwise snapping
    keeps every vertex and repairs self-intersections afterwards.
    """
    snapped = set_precision(geom, grid, mode="pointwise")
    if snapped.is_valid:
        return _polygon_list(snapped)
    return _polygon_list(make_valid(snapped))


def _edge_positions(frame):
    """Pixel-edge expressions shared by every neighbour.

    Pixel ``(col, row)`` covers ``[x0 + (col-0.5)/r, x0 + (col+0.5)/r]``;
    adjacent pixels evaluate the identical expression for their common edge.
    """

    def ex(k: int) -> float:
        return frame.x0 + (k - 0.5) / frame.r

    def ey(k: int) -> float:
        return frame.y0 + (k - 0.5) / frame.r

    return ex, ey


def _run_boxes(mask: np.ndarray, frame) -> list:
    """Exact rectangles for the horizontal pixel runs of a boolean mask."""
    ex, ey = _edge_positions(frame)
    rects = []
    for rw in np.nonzero(mask.any(axis=1))[0].tolist():
        cols = np.nonzero(mask[rw])[0]
        splits = np.nonzero(np.diff(cols) > 1)[0]
        starts = np.concatenate(([0], splits + 1))
        ends = np.concatenate((splits, [len(cols) - 1]))
        y0, y1 = ey(rw), ey(rw + 1)
        for s, e in zip(starts.tolist(), ends.tolist()):
            rects.append(box(ex(int(cols[s])), y0, ex(int(cols[e]) + 1), y1))
    return rects


def _union_polygons(parts: list) -> Polygon | MultiPolygon:
    """Union of polygon parts, guaranteed polygonal (or empty)."""
    polys = _polygon_list(safe_union(parts))
    if not polys:
        return MultiPolygon()
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)


# ---------------------------------------------------------------- step 7


def _ring_samples_dev(ring, other, step: float) -> float:
    """Max distance from dense samples of ``ring`` to ``other``."""
    coords = np.asarray(ring.segmentize(step).coords)
    if not len(coords):
        return 0.0
    return float(np.max(other.distance(_points(coords[:, 0], coords[:, 1]))))


def deviation(a, b, step: float = 0.005) -> float:
    """The Spec step-7 guard metric: ``hausdorff(original, simplified)``.

    GEOS ``hausdorff_distance`` on polygon arguments is unreliable for the
    degenerate borders the source carries: it returns values of ~0.2–0.4
    for geometries whose boundaries are everywhere within ~0.03 of each
    other (verified by dense sampling). This implementation measures the
    symmetric Hausdorff distance directly: both boundaries are densified
    to ``step`` and every sample is tested against the other polygon,
    which also catches collapsed parts and snap folds.
    """
    worst = 0.0
    for geom, other in ((a, b), (b, a)):
        for poly in _polygon_list(geom):
            for ring in (poly.exterior, *poly.interiors):
                worst = max(worst, _ring_samples_dev(ring, other, step))
    return worst


def _remove_ring_hairpins(coords, grid: float) -> list[tuple[float, float]]:
    """Drop vertices forming sub-grid needle folds (``p -> tip -> ~p``).

    MapChart source borders carry degenerate spikes: a ring walks more than
    ``2 * grid`` out and returns within ``grid`` of where it started. Such
    needles are thinner than the output grid — they cannot exist in the
    final geometry (``set_precision`` folds them into arbitrary blobs) —
    so they are removed before simplification. Removal repeats until the
    ring is stable (nested folds).
    """
    pts = [tuple(map(float, c)) for c in coords]
    if pts and pts[0] == pts[-1]:
        pts = pts[:-1]
    for _ in range(50):
        n = len(pts)
        if n < 4:
            return pts
        keep = []
        dropped = False
        for i in range(n):
            px, py = pts[i - 1]
            cx, cy = pts[i]
            qx, qy = pts[(i + 1) % n]
            back = math.hypot(qx - px, qy - py)
            out = math.hypot(cx - px, cy - py)
            if back <= grid and out > 2 * grid:
                dropped = True
                continue
            keep.append((cx, cy))
        pts = keep
        if not dropped:
            return pts
    return pts


def _clean_hairpins(geom, grid: float):
    """Apply needle removal to every ring of ``geom``."""
    parts = []
    for poly in _polygon_list(geom):
        ring = _remove_ring_hairpins(poly.exterior.coords, grid)
        if len(ring) < 3:
            continue
        interiors = [
            pts
            for hole in poly.interiors
            if len(pts := _remove_ring_hairpins(hole.coords, grid)) >= 3
        ]
        parts.append(Polygon(ring, interiors))
    if not parts:
        return MultiPolygon()
    return _union_polygons(parts)


def _finalize_land(
    source, tol: float, grid: float, factor: float = 0.0
) -> Polygon | MultiPolygon:
    """Per-part ``simplify`` + pointwise snap, then union.

    Each part is simplified and snapped on its own: a union-level snap can
    destroy the narrow channels and fjords a node's boundary forms (GEOS
    ``valid_output`` cleanup folds them into the interior, which moved one
    real province boundary by 0.43 units). Pointwise snapping keeps every
    vertex and repairs self-intersections afterwards; the final union is
    safe because it only merges the snapped parts' own coverage.

    Spec 1.10: a part's effective tolerance is
    ``min(tol, factor * sqrt(part.area))`` — small parts (islands) keep
    their detail instead of collapsing to triangles.
    """
    parts: list[Polygon] = []
    for part in sorted(
        _polygon_list(source), key=lambda p: (-p.area, p.bounds)
    ):
        part_tol = (
            tol if factor <= 0 else min(tol, factor * math.sqrt(part.area))
        )
        simplified = part.simplify(part_tol, preserve_topology=True)
        parts.extend(_snap_pointwise(simplified, grid))
    return _union_polygons(parts)


# Seam repair (map2_11): rings of one node whose boundaries coincide or run
# parallel within ``_SEAM_EPS`` along at least ``_SEAM_MIN_LEN`` are fused
# into ONE outer ring — the map2_9 seam-scan definition. Plain union first
# (covers exactly coincident edges); when a sliver gap or a needle hole
# remains, morphological closing with the smallest step that yields a
# single hole-free polygon is applied. Runs only on the node keys listed
# in ``overrides.seam_repair`` and only on the final (simplified) geometry.
_SEAM_EPS = 0.03
_SEAM_MIN_LEN = 0.05
_SEAM_CLOSING_STEPS = (0.02, 0.03, 0.045)
_SEAM_MAX_DRIFT = 0.005  # repaired group may change node area by <= 0.5 %


def _seam_length(a: Polygon, b: Polygon) -> float:
    """Length of ``b``'s boundary within ``_SEAM_EPS`` of ``a``'s."""
    return b.boundary.intersection(a.boundary.buffer(_SEAM_EPS)).length


def _seam_groups(parts: list[Polygon]) -> list[list[int]]:
    """Index groups of parts connected by seam runs (transitive closure)."""
    parent = list(range(len(parts)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            if (
                _seam_length(parts[i], parts[j]) >= _SEAM_MIN_LEN
                or _seam_length(parts[j], parts[i]) >= _SEAM_MIN_LEN
            ):
                pi, pj = _find(i), _find(j)
                if pi != pj:
                    parent[pi] = pj
    groups: dict[int, list[int]] = {}
    for i in range(len(parts)):
        groups.setdefault(_find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def _fuse_seam_group(group: list[Polygon], where: str) -> Polygon:
    """One outer ring for a seam group: union, else the smallest closing."""
    merged = safe_union(group)
    polys = _polygon_list(merged)
    if len(polys) == 1 and not polys[0].interiors:
        return polys[0]
    for step in _SEAM_CLOSING_STEPS:
        closed = _polygon_list(merged.buffer(step).buffer(-step))
        if len(closed) == 1 and not closed[0].interiors:
            return closed[0]
    raise PipelineError(
        GEOMETRY_INVALID,
        f"seam_repair {where}: the seam group cannot be fused into a "
        "single hole-free ring",
    )


def repair_seams(
    geom, key: str
) -> tuple[Polygon | MultiPolygon, list[str]] | None:
    """Fuse seam-joined rings of one node's final geometry.

    ``geom`` is the canonical (serialised-roundtrip) shape: stray interior
    rings that serialise as separate parts — the western_upper_swabia case —
    are real parts here, which is what the map2_9 seam scan measures.
    Returns ``(repaired_geometry, notes)`` or ``None`` when nothing was
    merged. Notes are report lines (parts fused, area drift).
    """
    parts = _polygon_list(geom)
    groups = _seam_groups(parts)
    if not groups:
        return None
    replaced: set[int] = set()
    fused: list[Polygon] = []
    notes: list[str] = []
    for group in groups:
        merged = _fuse_seam_group([parts[i] for i in group], key)
        drift = abs(
            merged.area - sum(parts[i].area for i in group)
        ) / max(geom.area, 1e-9)
        notes.append(
            f"{key}: fused {len(group)} rings "
            f"(area drift {drift * 100:.3f}%)"
        )
        fused.append(merged)
        replaced.update(group)
    kept = [p for i, p in enumerate(parts) if i not in replaced]
    out = _polygon_list(safe_union([*fused, *kept]))
    return (
        out[0] if len(out) == 1 else MultiPolygon(out),
        notes,
    )


def build_land_geometries(
    nodes: dict, cfg: PipelineConfig, seam_keys: frozenset[str] = frozenset()
) -> tuple[
    dict[str, Polygon | MultiPolygon],
    dict[str, float],
    list[str],
    list[str],
]:
    """Union, simplify and snap each land node (interior rings preserved).

    Source provinces can carry interior rings — lakes enclosed by a single
    province. They are water, not land (Spec 1.4), so the rings are kept;
    on the map they show the ``inland_water`` background through the hole.

    ``seam_keys`` lists the nodes of ``overrides.seam_repair`` (map2_11):
    after the simplify/snap guard passes, seam-joined rings of the final
    geometry are fused into one outer ring and re-checked against the same
    deviation and area guard.

    Returns ``(geometries, deviation, repairs, seam_notes)`` keyed by node
    key; the deviation maps the effective input (after needle cleanup, if
    it ran) to the final geometry and is bounded by ``simplify.tolerance +
    output.grid``. ``repairs`` lists node keys whose source contour needed
    degenerate-needle cleanup before the guard could pass; ``seam_notes``
    holds one report line per fused seam group.
    """
    tol = cfg.simplify.tolerance
    grid = cfg.output.grid
    bound = tol + grid
    geoms: dict[str, Polygon | MultiPolygon] = {}
    deviations: dict[str, float] = {}
    repairs: list[str] = []
    seam_notes: list[str] = []
    errors: list[PipelineError] = []
    for key in sorted(nodes):
        node = nodes[key]
        original = safe_union(list(node.parts))
        cleaned = _clean_hairpins(original, grid)
        if abs(cleaned.area - original.area) > 1e-9:
            repairs.append(key)
        area_limit = max(0.01, 0.02 * cleaned.area)

        def _ok(final, dev: float) -> bool:
            return (
                not final.is_empty
                and final.is_valid
                and dev <= bound
                and abs(final.area - cleaned.area) <= area_limit
            )

        final = _finalize_land(
            cleaned, tol, grid, cfg.simplify.small_part_factor
        )
        if final.is_empty:
            errors.append(
                PipelineError(
                    GEOMETRY_EMPTY,
                    f"land node {key!r}: geometry collapsed under "
                    "simplify/snap",
                )
            )
            continue
        dev = deviation(cleaned, final)
        if not _ok(final, dev):
            for finer in (tol / 2, tol / 4, 0.0):
                final = _finalize_land(
                    cleaned, finer, grid, cfg.simplify.small_part_factor
                )
                dev = deviation(cleaned, final)
                if _ok(final, dev):
                    break
            if not _ok(final, dev):
                errors.append(
                    PipelineError(
                        GEOMETRY_INVALID,
                        f"land node {key!r}: deviation {dev:.4f} "
                        f"(limit {bound}), area drift "
                        f"{abs(final.area - cleaned.area):.4f} "
                        f"(limit {area_limit:.4f}) even at reduced "
                        "tolerance",
                    )
                )
                continue
        if key in seam_keys:
            canon_parts = parse_path(dumps(final))
            canon = (
                canon_parts[0]
                if len(canon_parts) == 1
                else MultiPolygon(canon_parts)
            )
            res = repair_seams(canon, key)
            if res is not None:
                repaired, notes = res
                rep_dev = deviation(cleaned, repaired)
                drift = abs(repaired.area - final.area) / max(
                    final.area, 1e-9
                )
                if drift > _SEAM_MAX_DRIFT:
                    errors.append(
                        PipelineError(
                            GEOMETRY_INVALID,
                            f"seam_repair {key!r}: area drift "
                            f"{drift * 100:.3f}% exceeds 0.5%",
                        )
                    )
                    continue
                if not _ok(repaired, rep_dev):
                    errors.append(
                        PipelineError(
                            GEOMETRY_INVALID,
                            f"seam_repair {key!r}: repaired geometry "
                            f"fails the guard (deviation {rep_dev:.4f}, "
                            f"limit {bound}; area drift "
                            f"{abs(repaired.area - cleaned.area):.4f}, "
                            f"limit {area_limit})",
                        )
                    )
                    continue
                final, dev = repaired, rep_dev
                seam_notes.extend(notes)
        geoms[key] = final
        deviations[key] = float(dev)
    if errors:
        raise PipelineFailure(errors)
    return geoms, deviations, repairs, seam_notes


def build_land_mask(
    land_geoms: dict, prep, sea: SeaRaster, cfg: PipelineConfig
):
    """All land for the sea cut: included geometry + non-included land.

    ``(b)`` covers source provinces that are not game nodes (everything not
    in ``boundary.include``) plus the parts ``drop_parts`` removed from
    included provinces. ``technical_exclude`` entries never contribute.
    Non-included parts are simplified and snapped with the same settings as
    game land and closed by ``geometry.border_epsilon``. Spec 1.10: the
    included nodes contribute their final contours EXACTLY — the sea cut
    against this mask can never overlap a playable land rim or an island.
    """
    eps = cfg.geometry.border_epsilon
    tol = cfg.simplify.tolerance
    grid = cfg.output.grid
    frame_box = box(
        sea.frame.x0, sea.frame.y0, sea.frame.x1, sea.frame.y1
    )

    tech = set(prep.overrides.technical_exclude)
    node_by_name = {n.source_name: n for n in prep.nodes.values()}

    excluded = []
    for name in sorted(prep.geoms):
        if name.lower() in tech:
            continue
        node = node_by_name.get(name)
        if node is not None:
            kept = {id(p) for p in node.parts}
            parts = [p for p in prep.geoms[name] if id(p) not in kept]
        else:
            parts = prep.geoms[name]
        for part in parts:
            if not part.intersects(frame_box):
                continue
            simp = part.simplify(tol, preserve_topology=True)
            excluded.extend(_snap_pointwise(simp, grid))

    included = safe_union(
        [
            p
            for key in sorted(land_geoms)
            for p in _polygon_list(land_geoms[key])
        ]
    )
    closed = safe_union([p.buffer(eps) for p in excluded]).buffer(-eps)
    return safe_union(_polygon_list(included) + _polygon_list(closed))


def _grow_labels_into_land(sea: SeaRaster, dilate_pixels: int) -> np.ndarray:
    """``Zd``: land pixels within ``dilate_pixels`` of a label take it."""
    unlabelled = sea.labels == 0
    dist, indices = ndimage.distance_transform_edt(
        unlabelled, return_indices=True
    )
    grow = (sea.kinds == KIND_LAND) & unlabelled & (dist <= dilate_pixels)
    zd = sea.labels.copy()
    zd[grow] = sea.labels[indices[0][grow], indices[1][grow]]
    return zd


def _vertex_count(geom) -> int:
    return sum(
        len(p.exterior.coords) - 1
        + sum(len(r.coords) - 1 for r in p.interiors)
        for p in _polygon_list(geom)
    )


def _fill_leftover(
    zones: dict, land_mask, clip, sea: SeaRaster, cfg: PipelineConfig,
    zone_ids: dict,
) -> tuple[int, float, int, float]:
    """Merge small uncovered water pieces into the adjacent zone (Spec 1.5).

    Narrow inlets are deeper than the raster's 2-pixel growth, so the cut
    leaves slivers of water covered by neither land nor a zone — they
    render as ``outside``-coloured stains along coasts. Every leftover
    piece with ``area <= sea_cut.fill_max_area`` that touches a zone
    (within 0.05) and is not raster-lake or raster-bay is merged into the
    zone with the longest shared boundary (ties: smaller node id). The
    dict ``zones``
    is updated in place; the pieces keep their coverage-disjointness
    because ``leftover`` never overlaps a zone.

    Returns ``(merged_count, merged_area, leftover_count,
    leftover_area)`` where the leftover pair counts pieces still within
    ``fill_max_area`` that touch no zone at all.
    """
    limit = cfg.sea_cut.fill_max_area
    if limit <= 0:
        return 0, 0.0, 0, 0.0
    leftover = clip.difference(land_mask).difference(
        safe_union(list(zones.values()))
    )
    pieces = sorted(
        _polygon_list(leftover),
        key=lambda p: (p.bounds, -p.area),
    )
    assigned: dict[str, list] = {}
    merged_count = 0
    merged_area = 0.0
    left_count = 0
    left_area = 0.0
    for piece in pieces:
        if piece.area > limit:
            continue
        buf = piece.buffer(0.05)
        touching = [
            k for k in zones if buf.intersects(zones[k])
        ]
        if not touching:
            left_count += 1
            left_area += float(piece.area)
            continue
        rp = piece.representative_point()
        col, row = sea.frame.point_to_pixel(rp.x, rp.y)
        if (
            0 <= col < sea.frame.width
            and 0 <= row < sea.frame.height
            and int(sea.kinds[row, col]) in (KIND_LAKE, KIND_BAY)
        ):
            continue
        best = min(
            touching,
            key=lambda k: (
                -buf.intersection(zones[k].boundary).length,
                zone_ids.get(k, 1 << 30),
                k,
            ),
        )
        # The piece's land-facing edge carries the dense land-mask
        # boundary; a light simplify keeps the fill exact within ~0.2 px
        # at preview scale while dropping most of those vertices.
        fill_piece = piece.simplify(
            2 * cfg.output.grid, preserve_topology=True
        )
        if fill_piece.is_empty:
            fill_piece = piece
        assigned.setdefault(best, []).append(fill_piece)
        merged_count += 1
        merged_area += float(piece.area)

    for key in sorted(assigned):
        zone = _union_polygons([zones[key], *assigned[key]])
        snapped = _union_polygons(_snap_pointwise(zone, cfg.output.grid))
        if snapped.is_empty or not snapped.is_valid:
            raise PipelineError(
                GEOMETRY_INVALID,
                f"sea zone {key!r}: invalid geometry after leftover fill",
            )
        zones[key] = snapped
    return merged_count, merged_area, left_count, left_area


def build_sea_geometries(
    sea: SeaRaster, land_mask, cfg: PipelineConfig,
    clip=None, zone_ids: dict | None = None,
) -> SeaBuild:
    """Vectorise the zone raster, simplify as one coverage, cut by land.

    When ``clip`` (the playable bbox polygon) and ``zone_ids`` are given,
    small uncovered water pieces inside ``clip`` are merged into the
    adjacent zone afterwards (Spec 1.5 fjord fill).
    """
    frame = sea.frame
    zd = _grow_labels_into_land(sea, cfg.sea_cut.dilate_pixels)
    if sea.retired:
        # 1.9: retired zones emit no path — their pixels join the
        # unexplored-sea background inside `outside`.
        retired_idx = [
            i + 1
            for i, k in enumerate(sea.zone_keys)
            if k in sea.retired
        ]
        zd[np.isin(zd, retired_idx)] = 0

    boundaries = []
    for z in range(1, len(sea.zone_keys) + 1):
        region = safe_union(_run_boxes(zd == z, frame))
        boundaries.append(region.boundary)
    noded = unary_union(boundaries)

    face_items: list[tuple[int, object]] = []
    for face in polygonize(noded):
        rp = face.representative_point()
        col, row = frame.point_to_pixel(rp.x, rp.y)
        label = 0
        if 0 <= col < frame.width and 0 <= row < frame.height:
            label = int(zd[row, col])
        if label:
            face_items.append((label, face))
    face_items.sort(key=lambda lf: (lf[0], lf[1].bounds))
    faces = [f for _, f in face_items]

    if faces and not coverage_is_valid(faces):
        raise PipelineError(
            GEOMETRY_INVALID,
            "sea zone faces do not form a valid coverage "
            f"({len(faces)} faces)",
        )
    build = SeaBuild(face_count=len(faces), labelled_faces=len(faces))

    if faces:
        simplified = coverage_simplify(
            faces, cfg.simplify.sea_tolerance
        )
    else:
        simplified = []

    by_zone: dict[int, list] = {}
    for (label, _face), simple in zip(face_items, simplified):
        by_zone.setdefault(label, []).append(simple)

    errors: list[PipelineError] = []
    min_area = cfg.clean.min_part_area
    cut_zones: list = []
    cut_idx: list[int] = []  # zone index (1-based) of each cut_zones item
    for z, key in enumerate(sea.zone_keys, start=1):
        if key in sea.retired:
            continue
        parts = by_zone.get(z, [])
        if not parts:
            errors.append(
                PipelineError(
                    GEOMETRY_EMPTY, f"sea zone {key!r}: no coverage faces"
                )
            )
            continue
        zone = _union_polygons(parts)
        build.vertices_before_cut += _vertex_count(zone)
        build.area_before_cut += float(zone.area)
        diff = zone.difference(land_mask)
        kept = [p for p in _polygon_list(diff) if p.area >= min_area]
        if not kept:
            errors.append(
                PipelineError(
                    GEOMETRY_EMPTY,
                    f"sea zone {key!r}: empty after the land cut",
                )
            )
            continue
        cut_zones.append(_union_polygons(kept))
        cut_idx.append(z)
    if errors:
        raise PipelineFailure(errors)

    # Post-cut pass: the land cut replaced shared edges with the dense land
    # mask boundary, so the zones no longer tile simply. Re-run coverage
    # simplification on the cut zones together with their complement inside
    # the raster frame — the coverage invariant keeps every shared edge
    # identical vertex-for-vertex on both sides.
    frame_ext = box(
        sea.frame.x0 - 1.0, sea.frame.y0 - 1.0,
        sea.frame.x1 + 1.0, sea.frame.y1 + 1.0,
    )
    complement = frame_ext.difference(safe_union(list(cut_zones)))
    coverage = list(cut_zones) + ([] if complement.is_empty else [complement])
    if not coverage_is_valid(coverage):
        raise PipelineError(
            GEOMETRY_INVALID,
            "cut sea zones do not form a valid coverage",
        )
    simplified_zones = coverage_simplify(
        coverage, cfg.simplify.sea_tolerance
    )

    errors = []
    for i, z in enumerate(cut_idx):
        key = sea.zone_keys[z - 1]
        snapped = _union_polygons(
            _snap_pointwise(simplified_zones[i], cfg.output.grid)
        )
        if snapped.is_empty:
            errors.append(
                PipelineError(
                    GEOMETRY_EMPTY,
                    f"sea zone {key!r}: empty after grid snapping",
                )
            )
            continue
        if not snapped.is_valid:
            errors.append(
                PipelineError(
                    GEOMETRY_INVALID, f"sea zone {key!r}: invalid geometry"
                )
            )
            continue
        build.geoms[key] = snapped
        build.vertices_after_cut += _vertex_count(snapped)
        build.area_after_cut += float(snapped.area)
    if errors:
        raise PipelineFailure(errors)

    if clip is not None:
        (
            build.fill_merged,
            build.fill_merged_area,
            build.fill_leftover,
            build.fill_leftover_area,
        ) = _fill_leftover(
            build.geoms, land_mask, clip, sea, cfg, zone_ids or {},
        )
        build.vertices_after_cut = sum(
            _vertex_count(g) for g in build.geoms.values()
        )
        build.area_after_cut = sum(
            float(g.area) for g in build.geoms.values()
        )

    # 1.10: coverage simplification can push a zone edge back across a
    # land rim or an island; re-cut every zone by the exact land mask so
    # the sea never overlaps the final land contours.
    for key in sorted(build.geoms):
        diff = build.geoms[key].difference(land_mask)
        kept = [p for p in _polygon_list(diff) if p.area >= min_area]
        if not kept:
            raise PipelineError(
                GEOMETRY_EMPTY,
                f"sea zone {key!r}: empty after the exact land cut",
            )
        build.geoms[key] = _union_polygons(
            _snap_pointwise(_union_polygons(kept), cfg.output.grid)
        )
    build.vertices_after_cut = sum(
        _vertex_count(g) for g in build.geoms.values()
    )
    build.area_after_cut = sum(
        float(g.area) for g in build.geoms.values()
    )
    return build


# ---------------------------------------------------------------- step 8


def _nearest_grid_point_inside(
    part: Polygon, point: Point, grid: float
) -> tuple[float, float] | None:
    """Nearest ``grid`` point inside ``part`` around ``point`` (or None)."""
    ci = round(point.x / grid)
    cj = round(point.y / grid)
    limit = math.ceil(
        max(part.bounds[2] - part.bounds[0],
            part.bounds[3] - part.bounds[1]) / grid
    ) + 1
    for ring in range(0, limit + 1):
        found = []
        # Chebyshev ring of radius `ring`
        for di in range(-ring, ring + 1):
            for dj in range(-ring, ring + 1):
                if max(abs(di), abs(dj)) != ring:
                    continue
                x = (ci + di) * grid
                y = (cj + dj) * grid
                if part.covers(Point(x, y)):
                    found.append((di * di + dj * dj, x, y))
        if found:
            found.sort()
            _d, x, y = found[0]
            return (x, y)
    return None


# map2_6: a part holding this share of the node's area is "dominant" —
# the label anchors inside it; below it the label spans the whole group
# (island groups such as the Cyclades).
_LABEL_DOMINANT_SHARE = 0.6
# The multi-part label box covers this share of the group bounding box.
_LABEL_GROUP_SHARE = 0.9


def _chord_span(
    part: Polygon, x: float, y: float, axis: str
) -> tuple[float, float] | None:
    """Extent ``(lo, hi)`` of ``part``'s chord through ``(x, y)`` along
    ``axis`` — the segment of the y=const (``"x"``) or x=const (``"y"``)
    line inside ``part`` that contains the anchor coordinate. A
    non-convex part may cross the line in several segments; only the one
    holding the anchor is the box the label can actually sit in."""
    minx, miny, maxx, maxy = part.bounds
    if axis == "x":
        line = LineString([(minx - 1.0, y), (maxx + 1.0, y)])
        anchor = x
    else:
        line = LineString([(x, miny - 1.0), (x, maxy + 1.0)])
        anchor = y
    inter = part.intersection(line)
    if inter.is_empty:
        return None
    best: tuple[float, float] | None = None
    for seg in shapely.get_parts(inter):
        if seg.is_empty or seg.geom_type != "LineString":
            continue
        # Coordinate range of the segment along the axis.
        lo, hi = (
            (seg.bounds[0], seg.bounds[2])
            if axis == "x"
            else (seg.bounds[1], seg.bounds[3])
        )
        if lo - 1e-9 <= anchor <= hi + 1e-9:
            if best is None or hi - lo > best[1] - best[0]:
                best = (lo, hi)
    return best


def _centred_chord(
    part: Polygon, x: float, y: float, axis: str
) -> float:
    """Width of the chord containing the anchor, clipped symmetric
    around it: text centred on the pole can only occupy
    ``2 × min(anchor − lo, hi − anchor)`` without crossing the shore."""
    anchor = x if axis == "x" else y
    span = _chord_span(part, x, y, axis)
    if span is None:
        return 0.0
    lo, hi = span
    return max(0.0, 2.0 * min(anchor - lo, hi - anchor))


def label_box(geom, grid: float) -> tuple[float, float, float, float]:
    """``(x, y, w, h)`` label box of one final node geometry (map2_6).

    Dominant part (>= ``_LABEL_DOMINANT_SHARE`` of the node area):
    ``x, y`` is the pole of inaccessibility of that part and ``w``/``h``
    are the horizontal/vertical chords of the part through it — the
    widest free span the name may occupy inside one landmass. Otherwise
    (a true island group) the anchor is the area-weighted centre of the
    parts — it may lie over the water between them — and ``w``/``h`` are
    ``_LABEL_GROUP_SHARE`` of the group bounding box.
    """
    parts = _polygon_list(geom)
    total = float(sum(p.area for p in parts))
    largest = max(parts, key=lambda p: (p.area, tuple(-b for b in p.bounds)))
    if total > 0 and largest.area >= _LABEL_DOMINANT_SHARE * total:
        pole = polylabel(largest, tolerance=grid)
        x, y = round(pole.x, 2), round(pole.y, 2)
        if not largest.covers(Point(x, y)):
            rp = largest.representative_point()
            x, y = round(rp.x, 2), round(rp.y, 2)
        # Single-part and dominant-part anchors must sit inside the
        # polygon — a label never starts over water.
        assert largest.covers(Point(x, y)), (
            f"label anchor ({x}, {y}) outside its dominant part"
        )
        # The rendered box is centred on the anchor, so the usable
        # span is the chord clipped to its shorter side — a centred
        # label can never cross the shore (map2_6).
        w = _centred_chord(largest, x, y, "x")
        h = _centred_chord(largest, x, y, "y")
    else:
        cx = sum(p.area * p.centroid.x for p in parts) / total
        cy = sum(p.area * p.centroid.y for p in parts) / total
        x, y = round(cx, 2), round(cy, 2)
        minx, miny, maxx, maxy = geom.bounds
        # The box is centred on the weighted centre; when that centre
        # sits near a group-bbox edge (one big island on one side) the
        # full 0.9 share would spill over the edge — clip it symmetric
        # just like a single-part chord.
        w = _LABEL_GROUP_SHARE * 2.0 * min(cx - minx, maxx - cx)
        h = _LABEL_GROUP_SHARE * 2.0 * min(cy - miny, maxy - cy)
    # The loader contract is w, h > 0 — a degenerate sliver still gets
    # one grid cell rather than a zero the backend would reject.
    return (x, y, round(max(w, grid), 2), round(max(h, grid), 2))


# map2_20: the label spine — the name rides a straight or gently bent
# baseline inscribed in the territory (the dominant part by rule 5 of
# map2_6, or the group's convex hull when no part dominates). Chord
# candidates are scanned in the (u, v) frame: u along the chord
# direction, v along its left normal; every test is a ray crossing over
# the rotated edge arrays.


@dataclass
class NodeSpine:
    """``spine`` (x0, y0, x1, y1 + signed sagitta ``s`` in map units —
    the quadratic-Bézier control point is the chord midpoint moved by
    2·s along the chord's left normal), ``len`` (chord length) and
    ``thick`` (minimum thickness across the spine over its central
    share)."""

    spine: tuple[float, float, float, float, float]
    len: float
    thick: float


def _spine_territory(geom):
    """The polygon the spine must stay inside: the dominant part, or
    the group convex hull when no part dominates (rule 5 of map2_6)."""
    parts = _polygon_list(geom)
    total = float(sum(p.area for p in parts))
    largest = max(parts, key=lambda p: (p.area, tuple(-b for b in p.bounds)))
    dominant = total > 0 and largest.area >= _LABEL_DOMINANT_SHARE * total
    if len(parts) > 1 and not dominant:
        hull = geom.convex_hull
        if hull.area <= 0:
            return largest
        return hull
    return largest


def _spine_rings(geom) -> list:
    """All rings (exterior + holes) of the territory as Nx2 arrays."""
    rings = []
    for p in _polygon_list(geom):
        rings.append(np.asarray(p.exterior.coords, dtype=float))
        rings.extend(
            np.asarray(r.coords, dtype=float) for r in p.interiors
        )
    return rings


def _edges_uv(rings, du: np.ndarray) -> np.ndarray:
    """Edges as (u1, v1, u2, v2) rows in the frame with u along ``du``
    and v along its left normal (-du.y, du.x)."""
    dn = np.array([-du[1], du[0]])
    rows = []
    for ring in rings:
        us = ring @ du
        vs = ring @ dn
        rows.append(
            np.stack((us[:-1], vs[:-1], us[1:], vs[1:]), axis=1)
        )
    return np.concatenate(rows)


def _ray_crossings(
    edges: np.ndarray, pu: float, pv: float, d: np.ndarray
) -> np.ndarray:
    """Sorted signed distances along direction ``d`` where the line
    through (pu, pv) crosses the edges. Vertex hits count once via the
    half-open edge parameter."""
    ex = edges[:, 2] - edges[:, 0]
    ey = edges[:, 3] - edges[:, 1]
    den = d[0] * ey - d[1] * ex
    good = np.abs(den) > 1e-12
    wx = edges[:, 0] - pu
    wy = edges[:, 1] - pv
    t = np.where(good, (wx * ey - wy * ex) / np.where(good, den, 1.0), 0.0)
    s = np.where(good, (wx * d[1] - wy * d[0]) / np.where(good, den, 1.0), -1.0)
    hits = good & (s >= 0.0) & (s < 1.0)
    return np.sort(t[hits])


def _inside_uv(edges: np.ndarray, pu: float, pv: float) -> bool:
    """Point-in-polygon via a +u ray: odd number of crossings ahead.
    Parity needs no sort — just the count of crossings with t > 0."""
    ex = edges[:, 2] - edges[:, 0]
    ey = edges[:, 3] - edges[:, 1]
    den = ey  # d = (1, 0): den = 1*ey - 0*ex
    good = np.abs(den) > 1e-12
    wx = edges[:, 0] - pu
    wy = edges[:, 1] - pv
    t = np.where(good, (wx * ey - wy * ex) / np.where(good, den, 1.0), 0.0)
    s = np.where(good, -wy / np.where(good, den, 1.0), -1.0)
    hits = good & (s >= 0.0) & (s < 1.0) & (t > 1e-9)
    return int(hits.sum()) % 2 == 1


def _dist_to_edges(edges: np.ndarray, pu: float, pv: float) -> float:
    """Euclidean distance from (pu, pv) to the nearest edge."""
    ax = edges[:, 0] - pu
    ay = edges[:, 1] - pv
    ex = edges[:, 2] - edges[:, 0]
    ey = edges[:, 3] - edges[:, 1]
    ee = ex * ex + ey * ey
    t = np.clip(
        np.divide(-(ax * ex + ay * ey), ee, out=np.zeros_like(ee),
                  where=ee > 0.0),
        0.0, 1.0,
    )
    dx = ax + t * ex
    dy = ay + t * ey
    return float(np.sqrt((dx * dx + dy * dy).min()))


def _thickness_at(
    edges: np.ndarray, pu: float, pv: float, d: np.ndarray
) -> float:
    """Thickness at a spine point: twice the distance from the point to
    the boundary, bounded by the width of the polygon across the chord
    (direction ``d``). A chord sitting on the boundary itself scores
    ~0 here, so the scan prefers centred baselines."""
    ex = edges[:, 2] - edges[:, 0]
    ey = edges[:, 3] - edges[:, 1]
    den = d[0] * ey - d[1] * ex
    good = np.abs(den) > 1e-12
    wx = edges[:, 0] - pu
    wy = edges[:, 1] - pv
    t = np.where(good, (wx * ey - wy * ex) / np.where(good, den, 1.0), 0.0)
    s = np.where(good, (wx * d[1] - wy * d[0]) / np.where(good, den, 1.0), -1.0)
    t = t[good & (s >= 0.0) & (s < 1.0)]
    fwd = t[t > 1e-9]
    bwd = t[t < -1e-9]
    if not fwd.size or not bwd.size:
        return 0.0
    # nearest crossings only — the sorted _ray_crossings would do more
    # work than this min/max pair.
    width = float(fwd.min() - bwd.max())
    return min(2.0 * _dist_to_edges(edges, pu, pv), width)


_UV_U = np.array([1.0, 0.0])
_UV_V = np.array([0.0, 1.0])


def _chords_at_offsets(
    edges: np.ndarray, offsets: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Longest inside segment on every scanline v=offsets[i].

    Returns ``(t0, t1, lens, mid_bound, found)`` — u-coordinates of the
    longest inside chord per scanline (``lens`` 0 where the line misses
    the territory) and ``mid_bound``, the length of the polygon segment
    containing the chord midpoint (an upper bound on its thickness).
    """
    lo = np.minimum(edges[:, 1], edges[:, 3])
    hi = np.maximum(edges[:, 1], edges[:, 3])
    mask = (lo[:, None] <= offsets[None, :]) & (
        offsets[None, :] < hi[:, None]
    )
    du_e = edges[:, 2] - edges[:, 0]
    dv_e = edges[:, 3] - edges[:, 1]
    slope = np.divide(
        du_e, dv_e, out=np.zeros_like(du_e), where=dv_e != 0.0
    )
    u_cross = np.where(
        mask,
        edges[:, 0][:, None]
        + (offsets[None, :] - edges[:, 1][:, None]) * slope[:, None],
        np.inf,
    )
    u_sorted = np.sort(u_cross, axis=0)
    if u_sorted.shape[0] % 2:
        # odd edge count → pad so every pair row exists
        u_sorted = np.concatenate(
            [u_sorted, np.full((1, u_sorted.shape[1]), np.inf)]
        )
    starts = u_sorted[0::2]
    ends = u_sorted[1::2]
    both = np.isfinite(starts) & np.isfinite(ends)
    seg_len = np.subtract(
        ends, starts, out=np.zeros_like(ends), where=both
    )
    i = np.argmax(seg_len, axis=0)
    col = np.arange(offsets.shape[0])
    t0 = starts[i, col]
    t1 = ends[i, col]
    lens = np.subtract(
        t1, t0, out=np.zeros_like(t0), where=np.isfinite(t0 + t1)
    )

    # the segment containing each chord's midpoint bounds its thickness
    mid = (t0 + t1) * 0.5
    covers_mid = (starts <= mid[None, :]) & (mid[None, :] < ends) & both
    mid_bound = np.where(covers_mid, seg_len, 0.0).max(axis=0)
    return t0, t1, lens, mid_bound, lens > 0.0


def _thickness_samples(
    edges: np.ndarray,
    t0: float,
    t1: float,
    o: float,
    sag: float,
    cfg: PipelineConfig,
) -> float:
    """Min thickness across the spine over the chord's central share,
    measured along the straight chord (sag=0) or the arc normals."""
    sc = cfg.spine
    margin = 0.5 * (1.0 - sc.central_share)
    best = math.inf
    for i in range(sc.thickness_samples):
        t = margin + sc.central_share * i / (sc.thickness_samples - 1)
        u = t0 + t * (t1 - t0)
        v = o + 4.0 * sag * t * (1.0 - t)
        if sag == 0.0:
            d = _UV_V
        else:
            tx = t1 - t0
            ty = 4.0 * sag * (1.0 - 2.0 * t)
            n = math.hypot(tx, ty)
            d = np.array([-ty / n, tx / n])
        best = min(best, _thickness_at(edges, u, v, d))
    return 0.0 if not math.isfinite(best) else best


def _arc_inside(
    edges: np.ndarray, t0: float, t1: float, o: float, sag: float,
    cfg: PipelineConfig,
) -> bool:
    """Fast containment of the arc's interior samples (endpoints sit on
    the boundary and are verified exactly on the winner)."""
    n = cfg.spine.arc_samples
    for i in range(1, n - 1):
        t = i / (n - 1)
        u = t0 + t * (t1 - t0)
        v = o + 4.0 * sag * t * (1.0 - t)
        if not _inside_uv(edges, u, v):
            return False
    return True


def _arc_linestring(t0: float, t1: float, o: float, sag: float, cfg) -> LineString:
    """The full arc (endpoints included) as a LineString in (u, v)."""
    n = cfg.spine.arc_samples
    pts = [
        (t0 + (i / (n - 1)) * (t1 - t0),
         o + 4.0 * sag * (i / (n - 1)) * (1.0 - i / (n - 1)))
        for i in range(n)
    ]
    return LineString(pts)


def spine_of_node(geom, cfg: PipelineConfig) -> NodeSpine:
    """Scan inscribed chords/arcs and keep the one maximising
    ``len × thick``; the spine never leaves the territory.

    Per angle the chords of all scanlines are found in one vectorised
    pass; the expensive thickness/arc measurements only run for chords
    whose ``len × mid-bound`` could still beat the current best, and
    arc variants only for the four best straight chords of the angle.
    The eight best candidates overall get an exact shapely containment
    check (the fast parity test treats boundary points loosely)."""
    sc = cfg.spine
    grid = cfg.output.grid
    territory = _spine_territory(geom)
    rings = _spine_rings(territory)

    top: list[tuple] = []  # (score, order, ang, t0, t1, o, sag)
    order = 0
    best = 0.0

    def consider(score: float, ang, t0, t1, o, sag):
        nonlocal order, best
        if score > best:
            best = score
        top.append((score, order, ang, t0, t1, o, sag))
        order += 1
        top.sort(key=lambda r: (-r[0], r[1]))
        del top[8:]

    k_max = int(math.floor(sc.max_angle_deg / sc.angle_step_deg))
    for k in range(0, k_max + 1):
        for sign in ((1,) if k == 0 else (1, -1)):
            ang = math.radians(k * sc.angle_step_deg * sign)
            du = np.array([math.cos(ang), math.sin(ang)])
            edges = _edges_uv(rings, du)
            v_lo = float(np.minimum(edges[:, 1], edges[:, 3]).min())
            v_hi = float(np.maximum(edges[:, 1], edges[:, 3]).max())
            o0 = math.floor(v_lo / sc.offset_step + 0.5) * sc.offset_step
            offs = np.arange(o0, v_hi + 1e-9, sc.offset_step)
            if not offs.size:
                continue
            straights: list[tuple] = []
            # chunk the E×O crossing matrix for very large territories
            step = max(1, int(2_000_000 / max(edges.shape[0], 1)))
            for c0 in range(0, offs.size, step):
                t0s, t1s, lens, midb, found = _chords_at_offsets(
                    edges, offs[c0 : c0 + step]
                )
                live = np.nonzero(found & (lens * midb > best))[0]
                # only the most promising chords are measured —
                # len × mid_bound is an upper bound on the score;
                # ties keep offset order so a bound plateau is sampled
                # spread out (the centred chord is always reached)
                rank = np.argsort(-(lens * midb)[live], kind="stable")
                if live.size > 12:
                    pick = np.unique(np.concatenate((
                        np.arange(6),
                        np.linspace(5, live.size - 1, 7).astype(int),
                    )))
                    live = live[rank[pick]]
                else:
                    live = live[rank]
                for j in live:
                    t0, t1, o = (
                        float(t0s[j]), float(t1s[j]), float(offs[c0 + j])
                    )
                    thick = _thickness_samples(
                        edges, t0, t1, o, 0.0, cfg
                    )
                    score = float(lens[j]) * thick
                    if score > 0.0:
                        straights.append((score, ang, t0, t1, o))
            straights.sort(key=lambda r: -r[0])
            for score, ang, t0, t1, o in straights:
                consider(score, ang, t0, t1, o, 0.0)
            # arcs: only the most promising chords bend worth testing
            for score, ang, t0, t1, o in straights[:4]:
                if score * 4.0 <= best:
                    continue
                for frac in (0.5, -0.5, 1.0, -1.0):
                    sag = frac * sc.max_bend * (t1 - t0)
                    if not _arc_inside(edges, t0, t1, o, sag, cfg):
                        continue
                    thick = _thickness_samples(
                        edges, t0, t1, o, sag, cfg
                    )
                    score = (t1 - t0) * thick
                    if score > 0.0:
                        consider(score, ang, t0, t1, o, sag)

    tol = territory.buffer(grid * 0.5)
    for _, _, ang, t0, t1, o, sag in top:
        du = np.array([math.cos(ang), math.sin(ang)])
        dn = np.array([-du[1], du[0]])
        edges = _edges_uv(rings, du)
        arc_uv = _arc_linestring(t0, t1, o, sag, cfg)
        pts = np.asarray(arc_uv.coords)  # (u, v)
        xy = pts[:, :1] * du + pts[:, 1:] * dn
        arc_xy = LineString(xy)
        if not tol.covers(arc_xy):
            continue
        p0 = np.asarray(arc_xy.coords[0])
        p1 = np.asarray(arc_xy.coords[-1])
        thick = _thickness_samples(edges, t0, t1, o, sag, cfg)
        len_out = max(round(t1 - t0, 2), grid)
        # the emitted pair must satisfy |s|/len <= max_bend even after
        # the 0.01 rounding — clamp the sagitta to the rounded limit
        cap = math.floor(sc.max_bend * len_out * 100 + 1e-6) / 100
        sag_out = max(-cap, min(cap, round(sag, 2)))
        spine = (
            float(round(p0[0], 2)), float(round(p0[1], 2)),
            float(round(p1[0], 2)), float(round(p1[1], 2)),
            float(sag_out),
        )
        return NodeSpine(
            spine=spine,
            len=len_out,
            thick=max(round(thick, 2), grid),
        )

    # Degenerate territory: a grid-long horizontal stub at the
    # representative point keeps the manifest fields present.
    p = geom.representative_point()
    spine = (
        round(p.x - grid, 2), round(p.y, 2),
        round(p.x + grid, 2), round(p.y, 2), 0.0,
    )
    return NodeSpine(spine=spine, len=2 * grid, thick=grid)


def node_metrics(geom, cfg: PipelineConfig) -> NodeMetrics:
    """``anchor``, ``bbox``, ``area`` and ``label`` of one final node geometry."""
    grid = cfg.output.grid
    parts = _polygon_list(geom)
    largest = max(parts, key=lambda p: (p.area, tuple(-b for b in p.bounds)))

    mic = maximum_inscribed_circle(largest, tolerance=grid)
    cx, cy = mic.coords[0]
    centre = Point(cx, cy)
    if not largest.covers(centre):
        centre = largest.representative_point()
    ax, ay = round(centre.x, 2), round(centre.y, 2)
    if not largest.covers(Point(ax, ay)):
        rp = largest.representative_point()
        snapped = _nearest_grid_point_inside(largest, rp, grid)
        if snapped is not None:
            ax, ay = snapped
        else:
            ax, ay = rp.x, rp.y

    minx, miny, maxx, maxy = geom.bounds
    bbox = (
        round(math.floor(minx / grid + 1e-9) * grid, 2),
        round(math.floor(miny / grid + 1e-9) * grid, 2),
        round(math.ceil(maxx / grid - 1e-9) * grid, 2),
        round(math.ceil(maxy / grid - 1e-9) * grid, 2),
    )
    return NodeMetrics(
        anchor=(ax, ay),
        bbox=bbox,
        area=round(geom.area, 2),
        label=label_box(geom, grid),
        spine=spine_of_node(geom, cfg),
    )


# ---------------------------------------------------------------- step 9


def build_lake_region(
    sea: SeaRaster, land_mask, view_poly, cfg, land_union=None,
    nodes_u=None,
):
    """Lake raster grown 1 px, clipped to exact water (viewBox - LandMask).

    Spec 1.5: only lakes within ``outside.lake_near_land`` of the final
    included land become ``outside`` windows — lakes inside excluded
    territory stay dark. Spec 1.10: a water body that touches no node
    (within ``geometry.border_epsilon``) is not cut out at all. Returns
    ``(region, pieces, area, spill, dropped_count, dropped_area)``.
    """
    rects = _run_boxes(sea.kinds == KIND_LAKE, sea.frame)
    empty = (None, 0, 0.0, 0.0, 0, 0.0)
    if not rects:
        return empty
    grown = safe_union(rects).buffer(
        1.0 / sea.frame.r, join_style="mitre"
    )
    exact_water = view_poly.difference(land_mask)
    region = grown.intersection(exact_water)
    pieces = [
        p for p in _polygon_list(region)
        if p.area >= cfg.outside.min_hole_area
    ]
    dropped = []
    if land_union is not None:
        near = cfg.outside.lake_near_land
        keep = [p for p in pieces if p.distance(land_union) <= near]
        dropped = [p for p in pieces if p.distance(land_union) > near]
        pieces = keep
    if nodes_u is not None:
        eps = cfg.geometry.border_epsilon
        keep = [p for p in pieces if p.distance(nodes_u) <= eps]
        dropped += [p for p in pieces if p.distance(nodes_u) > eps]
        pieces = keep
    if not pieces:
        return (
            None, 0, 0.0, 0.0,
            len(dropped), sum(float(p.area) for p in dropped),
        )
    region = _union_polygons(pieces)
    spill_mask = mask_from_geometry(region, sea.frame)
    spill = float(
        np.count_nonzero(spill_mask & (sea.kinds != KIND_LAKE))
    ) / (sea.frame.r * sea.frame.r)
    return (
        region, len(pieces), float(region.area), spill,
        len(dropped), sum(float(p.area) for p in dropped),
    )


def build_bay_region(
    sea: SeaRaster, land_mask, view_poly, cfg: PipelineConfig,
    nodes_u=None,
):
    """Bay raster grown 1 px, clipped to exact water (viewBox - LandMask).

    Step 5a/Appendix A step 9: every bay piece of at least
    ``outside.min_hole_area`` that touches a node (within
    ``geometry.border_epsilon``) becomes a window in ``outside`` and is
    exported as the ``sea_water`` path. Spec 1.10: a bay touching no node
    stays dark inside excluded land.
    """
    rects = _run_boxes(sea.kinds == KIND_BAY, sea.frame)
    if not rects:
        return None
    grown = safe_union(rects).buffer(
        1.0 / sea.frame.r, join_style="mitre"
    )
    region = grown.intersection(view_poly.difference(land_mask))
    pieces = [
        p
        for p in _polygon_list(region)
        if p.area >= cfg.outside.min_hole_area
    ]
    if nodes_u is not None:
        eps = cfg.geometry.border_epsilon
        pieces = [p for p in pieces if p.distance(nodes_u) <= eps]
    if not pieces:
        return None
    return _union_polygons(pieces)


def build_outside(
    node_geoms: list,
    lake_region,
    view_poly,
    cfg: PipelineConfig,
    bay_region=None,
) -> OutsideBuild:
    """``outside`` = viewBox − buffer(N, −underlap) − lakeRegion − deep pad.

    ``deep = buffer(N, −0.2)`` is the spec invariant boundary: ``outside``
    must not intersect it. On dense real geometry GEOS offset curves are
    not reliably nested, so ``buffer(N, −underlap)`` alone leaves fjord
    pockets poking into ``deep``; the padded deep contour is subtracted
    explicitly (pad ``1.5 * grid`` so the invariant still holds exactly
    after grid snapping).

    The outside contour is intentionally NOT simplified: its inner edge
    follows the closed node union (coast/zone detail) and the lake windows
    keep their raster resolution; the Spec step 9 wording applies
    ``simplify.tolerance`` to node contours, not to ``outside``.

    ``n`` is unioned from the *exploded* part list in the caller's
    canonical order (sorted node keys, parts by descending area — the same
    order ``dumps`` writes and tests re-parse): GEOS offset curves on a
    ~100k-vertex union are numerically sensitive to input structure, so
    reproducing ``buffer(N, -0.2)`` bit-exactly requires the identical
    item order.
    """
    n = safe_union(
        [p for g in node_geoms for p in _polygon_list(g)]
    )
    n = n.buffer(cfg.outside.closing).buffer(-cfg.outside.closing)
    n_inset = n.buffer(-cfg.outside.underlap)
    deep_pad = n.buffer(-0.2).buffer(1.5 * cfg.output.grid)

    outside = view_poly.difference(n_inset)
    if lake_region is not None and not lake_region.is_empty:
        outside = outside.difference(lake_region)
    if bay_region is not None and not bay_region.is_empty:
        outside = outside.difference(bay_region)
    if not deep_pad.is_empty:
        outside = outside.difference(deep_pad)

    # A kept lake inside a small unclaimed pocket leaves a dark rim of
    # ``outside`` around its window; the pocket is the same inland water
    # body, so it joins the window. Lakes in excluded land were dropped
    # from ``lake_region`` — their pockets are not touched.
    lake_rims = 0
    lake_rims_area = 0.0
    if lake_region is not None and not lake_region.is_empty:
        near_lake = lake_region.buffer(0.05)
        rims = [
            p for p in _polygon_list(outside)
            if p.area < _FRAGMENT_MAX_AREA
            and near_lake.covers(p.representative_point())
        ]
        if rims:
            lake_rims = len(rims)
            lake_rims_area = sum(float(p.area) for p in rims)
            outside = outside.difference(safe_union(rims))

    holes_dropped = 0
    cleaned: list[Polygon] = []
    for part in _polygon_list(outside):
        keep = []
        for ring in part.interiors:
            hole = Polygon(ring)
            if hole.area >= cfg.outside.min_hole_area:
                keep.append(ring)
            elif (
                lake_region is not None
                and not lake_region.is_empty
                and lake_region.covers(hole.representative_point())
            ) or (
                bay_region is not None
                and not bay_region.is_empty
                and bay_region.covers(hole.representative_point())
            ):
                keep.append(ring)  # water windows stay whatever the size
            else:
                holes_dropped += 1
        cleaned.append(
            Polygon(part.exterior.coords, [r.coords for r in keep])
        )
    if not cleaned:
        raise PipelineError(GEOMETRY_EMPTY, "outside geometry is empty")

    parts: list[Polygon] = []
    for part in _polygon_list(safe_union(cleaned)):
        parts.extend(_snap_pointwise(part, cfg.output.grid))
    snapped = _union_polygons(parts)

    # Filling a small hole above re-covers whatever occupied it — a pocket
    # inside ``deep_pad`` included. Cut it again; the pad margin exceeds
    # the re-snap rounding error, so the invariant still holds exactly.
    if not deep_pad.is_empty:
        parts = []
        for part in _polygon_list(snapped.difference(deep_pad)):
            parts.extend(_snap_pointwise(part, cfg.output.grid))
        snapped = _union_polygons(parts)

    if snapped.is_empty:
        raise PipelineError(GEOMETRY_EMPTY, "outside geometry is empty")
    if not snapped.is_valid:
        raise PipelineError(
            GEOMETRY_INVALID, "outside geometry invalid after snap"
        )

    lake_windows = 0
    if lake_region is not None and not lake_region.is_empty:
        for piece in _polygon_list(lake_region):
            if not snapped.covers(piece.representative_point()):
                lake_windows += 1
    lake_holes = sum(
        1
        for part in _polygon_list(snapped)
        for ring in part.interiors
        if lake_region is not None
        and not lake_region.is_empty
        and lake_region.covers(Polygon(ring).representative_point())
    )
    return OutsideBuild(
        outside=snapped, nodes_union=n, lake_region=lake_region,
        holes_dropped=holes_dropped, lake_windows=lake_windows,
        lake_holes=lake_holes,
        lake_rims=lake_rims, lake_rims_area=lake_rims_area,
    )
