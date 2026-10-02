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
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

from .errors import (
    GEOMETRY_EMPTY,
    GEOMETRY_INVALID,
    PipelineError,
    PipelineFailure,
)
from .pipeline_config_schema import PipelineConfig
from .seas import KIND_LAKE, KIND_LAND, SeaRaster, mask_from_geometry
from .svgpath import polygons_of
from .svg_source import safe_union


@dataclass
class NodeMetrics:
    """Per-node ``anchor``, ``bbox`` and ``area`` for the manifest."""

    anchor: tuple[float, float]
    bbox: tuple[float, float, float, float]
    area: float


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
    source, tol: float, grid: float
) -> Polygon | MultiPolygon:
    """Per-part ``simplify`` + pointwise snap, then union.

    Each part is simplified and snapped on its own: a union-level snap can
    destroy the narrow channels and fjords a node's boundary forms (GEOS
    ``valid_output`` cleanup folds them into the interior, which moved one
    real province boundary by 0.43 units). Pointwise snapping keeps every
    vertex and repairs self-intersections afterwards; the final union is
    safe because it only merges the snapped parts' own coverage.
    """
    parts: list[Polygon] = []
    for part in sorted(
        _polygon_list(source), key=lambda p: (-p.area, p.bounds)
    ):
        simplified = part.simplify(tol, preserve_topology=True)
        parts.extend(_snap_pointwise(simplified, grid))
    return _union_polygons(parts)


def build_land_geometries(
    nodes: dict, cfg: PipelineConfig
) -> tuple[dict[str, Polygon | MultiPolygon], dict[str, float], list[str]]:
    """Union, simplify and snap each land node (interior rings preserved).

    Source provinces can carry interior rings — lakes enclosed by a single
    province. They are water, not land (Spec 1.4), so the rings are kept;
    on the map they show the ``inland_water`` background through the hole.

    Returns ``(geometries, deviation, repairs)`` keyed by node key; the
    deviation maps the effective input (after needle cleanup, if it ran) to
    the final geometry and is bounded by ``simplify.tolerance +
    output.grid``. ``repairs`` lists node keys whose source contour needed
    degenerate-needle cleanup before the guard could pass.
    """
    tol = cfg.simplify.tolerance
    grid = cfg.output.grid
    bound = tol + grid
    geoms: dict[str, Polygon | MultiPolygon] = {}
    deviations: dict[str, float] = {}
    repairs: list[str] = []
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

        final = _finalize_land(cleaned, tol, grid)
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
                final = _finalize_land(cleaned, finer, grid)
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
        geoms[key] = final
        deviations[key] = float(dev)
    if errors:
        raise PipelineFailure(errors)
    return geoms, deviations, repairs


def build_land_mask(
    land_geoms: dict, prep, sea: SeaRaster, cfg: PipelineConfig
):
    """All land for the sea cut: included geometry + non-included land.

    ``(b)`` covers source provinces that are not game nodes (everything not
    in ``boundary.include``) plus the parts ``drop_parts`` removed from
    included provinces. ``technical_exclude`` entries never contribute.
    Non-included parts are simplified and snapped with the same settings as
    game land, then the whole mask is closed by ``geometry.border_epsilon``.
    """
    eps = cfg.geometry.border_epsilon
    tol = cfg.simplify.tolerance
    grid = cfg.output.grid
    frame_box = box(
        sea.frame.x0, sea.frame.y0, sea.frame.x1, sea.frame.y1
    )

    tech = set(prep.overrides.technical_exclude)
    node_by_name = {n.source_name: n for n in prep.nodes.values()}

    pieces = list(land_geoms.values())
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
            pieces.extend(_snap_pointwise(simp, grid))

    return safe_union([p.buffer(eps) for p in pieces]).buffer(-eps)


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


def build_sea_geometries(
    sea: SeaRaster, land_mask, cfg: PipelineConfig
) -> SeaBuild:
    """Vectorise the zone raster, simplify as one coverage, cut by land."""
    frame = sea.frame
    zd = _grow_labels_into_land(sea, cfg.sea_cut.dilate_pixels)

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
    for z, key in enumerate(sea.zone_keys, start=1):
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
    for i, key in enumerate(sea.zone_keys):
        if i >= len(cut_zones):
            continue
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


def node_metrics(geom, cfg: PipelineConfig) -> NodeMetrics:
    """``anchor``, ``bbox`` and ``area`` of one final node geometry."""
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
    return NodeMetrics(anchor=(ax, ay), bbox=bbox, area=round(geom.area, 2))


# ---------------------------------------------------------------- step 9


def build_lake_region(sea: SeaRaster, land_mask, view_poly, cfg):
    """Lake raster grown 1 px, clipped to exact water (viewBox - LandMask)."""
    rects = _run_boxes(sea.kinds == KIND_LAKE, sea.frame)
    if not rects:
        return None, 0, 0.0, 0.0
    grown = safe_union(rects).buffer(
        1.0 / sea.frame.r, join_style="mitre"
    )
    exact_water = view_poly.difference(land_mask)
    region = grown.intersection(exact_water)
    pieces = [
        p for p in _polygon_list(region)
        if p.area >= cfg.outside.min_hole_area
    ]
    if not pieces:
        return None, 0, 0.0, 0.0
    region = _union_polygons(pieces)
    spill_mask = mask_from_geometry(region, sea.frame)
    spill = float(
        np.count_nonzero(spill_mask & (sea.kinds != KIND_LAKE))
    ) / (sea.frame.r * sea.frame.r)
    return region, len(pieces), float(region.area), spill


def build_outside(
    node_geoms: list, lake_region, view_poly, cfg: PipelineConfig
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
    if not deep_pad.is_empty:
        outside = outside.difference(deep_pad)

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
            ):
                keep.append(ring)  # lake windows stay whatever the size
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
    )
