"""Appendix A step 5 for sea zones (Spec 3.2): the raster frame, water and
playable-land masks, the sea band, seed snapping, multi-source BFS and the
classification of every water body in the frame.

Pixel convention (fixed; tests rely on it): pixel ``(col, row)`` has its
centre at ``(x0 + col/r, y0 + row/r)``; a point ``(x, y)`` maps to pixel
``(round((x-x0)*r), round((y-y0)*r))``. Polygons are filled with PIL
``ImageDraw.polygon`` at coordinates ``((x-x0)*r, (y-y0)*r)``; holes are
re-drawn with value 0.

Deterministic by construction: fixed neighbour order in the BFS, sorted
iteration everywhere, no timestamps.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import Polygon, box

from .errors import (
    DATA_INVALID,
    SEED_OUTSIDE_WATER,
    UNSEEDED_WATER,
    WATER_OUTSIDE_INVALID,
    ZONE_EMPTY,
    PipelineError,
    PipelineFailure,
)
from .models import Overrides, VIEW_X_MAX, VIEW_Y_MAX
from .pipeline_config_schema import PipelineConfig
from .svg_source import safe_union

# 4-connectivity structuring element for component labelling.
_CROSS = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)
# 3x3 square element for the band closing.
_SQUARE3 = np.ones((3, 3), dtype=bool)
# BFS neighbour order (dx, dy): right, left, down, up.
_NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))

# Extra frame margin beyond sea_margin + sea_margin_smooth (Spec 3.2 step 1).
_FRAME_EXTRA = 1.0

KIND_LAND = 0
KIND_ZONE_WATER = 1
KIND_UNKNOWN_SEA = 2
KIND_LAKE = 3


@dataclass
class RasterFrame:
    """The raster window in source units and its pixel resolution."""

    x0: float
    y0: float
    x1: float
    y1: float
    r: int
    width: int
    height: int

    def point_to_pixel(self, x: float, y: float) -> tuple[int, int]:
        return (round((x - self.x0) * self.r), round((y - self.y0) * self.r))


@dataclass
class SnappedSeed:
    zone_key: str
    point: tuple[float, float]
    pixel: tuple[int, int]  # (col, row)
    distance: float  # units between the seed and the snapped pixel
    claimed: bool  # pixel already taken by an earlier seed


@dataclass
class Lake:
    area: float
    centroid: tuple[float, float]


@dataclass
class SeaRaster:
    frame: RasterFrame
    zone_keys: list[str]  # zone index order (index i -> zone i + 1)
    zone_name_ru: list[str]
    water: np.ndarray  # bool, W
    band: np.ndarray  # bool, B
    working: np.ndarray  # bool, W' = W & B
    land: np.ndarray  # bool, L
    playable: np.ndarray  # bool, I
    labels: np.ndarray  # int16, zone index per pixel, 0 = none
    kinds: np.ndarray  # uint8, per-pixel kind map
    zone_areas: list[float]  # sq. units per zone index
    # 1.9: retired zone keys — labels still claim water but the pixels are
    # KIND_UNKNOWN_SEA and no graph node/geometry path is emitted.
    retired: frozenset[str] = frozenset()
    snapped: list[SnappedSeed] = field(default_factory=list)
    lakes: list[Lake] = field(default_factory=list)
    water_outside: list[tuple[str, float]] = field(default_factory=list)
    unreached_small_count: int = 0
    unreached_small_area: float = 0.0


def _polygons(geom) -> list[Polygon]:
    """Flatten a (Multi)Polygon into its constituent polygons."""
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in geom.geoms if isinstance(g, Polygon)]


def fill_polygon(draw: ImageDraw.ImageDraw, poly: Polygon, fill: int,
                 frame: RasterFrame) -> None:
    """Draw one polygon's exterior with ``fill`` and its holes with 0."""
    r = frame.r
    draw.polygon(
        [((x - frame.x0) * r, (y - frame.y0) * r)
         for x, y in poly.exterior.coords],
        fill=fill,
    )
    for ring in poly.interiors:
        draw.polygon(
            [((x - frame.x0) * r, (y - frame.y0) * r)
             for x, y in ring.coords],
            fill=0,
        )


def mask_from_geometry(geom, frame: RasterFrame) -> np.ndarray:
    """Rasterise a (Multi)Polygon into a bool mask of the frame.

    Polygons are drawn largest first so that an island polygon sitting in a
    hole of a bigger polygon is painted over the hole, not erased by it.
    """
    img = Image.new("L", (frame.width, frame.height), 0)
    draw = ImageDraw.Draw(img)
    polys = _polygons(geom) if geom is not None else []
    for poly in sorted(polys, key=lambda p: -p.area):
        fill_polygon(draw, poly, 1, frame)
    return np.asarray(img, dtype=bool)


def _union_closed(parts: list[Polygon], epsilon: float):
    """``union(buffer(+eps)).buffer(-eps)``: close sub-pixel slivers."""
    if not parts:
        return None
    return safe_union([p.buffer(epsilon) for p in parts]).buffer(-epsilon)


def _compute_frame(nodes, overrides: Overrides, r: int) -> RasterFrame:
    xs0, ys0, xs1, ys1 = [], [], [], []
    for node in nodes.values():
        for part in node.parts:
            b = part.bounds
            xs0.append(b[0])
            ys0.append(b[1])
            xs1.append(b[2])
            ys1.append(b[3])
    if not xs0:
        raise PipelineError(
            DATA_INVALID, "no included land parts: playable bbox is empty"
        )
    m = overrides.sea_margin + overrides.sea_margin_smooth + _FRAME_EXTRA
    x0 = max(0.0, min(xs0) - m)
    y0 = max(0.0, min(ys0) - m)
    x1 = min(VIEW_X_MAX, max(xs1) + m)
    y1 = min(VIEW_Y_MAX, max(ys1) + m)
    return RasterFrame(
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        r=r,
        width=math.ceil((x1 - x0) * r),
        height=math.ceil((y1 - y0) * r),
    )


def _compute_band(playable: np.ndarray, overrides: Overrides,
                  r: int) -> np.ndarray:
    """Sea band B: pixels within ``sea_margin`` of playable land, smoothed."""
    if overrides.sea_margin_shape == "square":
        dist = ndimage.distance_transform_cdt(
            ~playable, metric="chessboard"
        ) / r
    else:
        dist = ndimage.distance_transform_edt(~playable) / r
    band = dist <= overrides.sea_margin
    s = overrides.sea_margin_smooth
    if s > 0:
        k = int(s * r)
        pad = k + 2
        padded = np.pad(band, pad, constant_values=False)
        closed = ndimage.binary_erosion(
            ndimage.binary_dilation(padded, structure=_SQUARE3,
                                    iterations=k),
            structure=_SQUARE3,
            iterations=k,
        )
        band = closed[pad:-pad, pad:-pad] | band
    return band


def _snap_seed(
    col: int, row: int, working: np.ndarray, frame: RasterFrame,
    snap_radius: float,
) -> tuple[tuple[int, int] | None, float]:
    """Snap a seed pixel to the nearest working-water pixel in the window.

    Returns ``((col, row), distance_units)`` or ``(None, inf)``. Ties break
    on the smaller row, then the smaller column.
    """
    h, w = working.shape
    if 0 <= col < w and 0 <= row < h and working[row, col]:
        return (col, row), 0.0
    k = round(snap_radius * frame.r)
    best: tuple[int, int] | None = None
    best_key = None
    for dr in range(-k, k + 1):
        rr = row + dr
        if rr < 0 or rr >= h:
            continue
        for dc in range(-k, k + 1):
            cc = col + dc
            if cc < 0 or cc >= w or not working[rr, cc]:
                continue
            key = (dr * dr + dc * dc, rr, cc)
            if best_key is None or key < best_key:
                best_key = key
                best = (cc, rr)
    if best is None:
        return None, math.inf
    return best, math.sqrt(best_key[0]) / frame.r


def _place_seeds(
    overrides: Overrides, working: np.ndarray, frame: RasterFrame,
    cfg: PipelineConfig,
) -> tuple[np.ndarray, list[int], list[SnappedSeed], list[PipelineError]]:
    """Label seed pixels in zone order; return labels, queue, records.

    A snapped pixel already claimed by an earlier seed is skipped (first
    claim wins). A seed with no working-water pixel in reach is
    ``SEED_OUTSIDE_WATER``; all seed errors are collected.
    """
    h, w = working.shape
    labels = np.zeros((h, w), dtype=np.int16)
    queue: list[int] = []  # flat pixel indices in seed order
    snapped: list[SnappedSeed] = []
    errors: list[PipelineError] = []
    for z, zone in enumerate(overrides.sea_zones, start=1):
        for seed in zone.seeds:
            col, row = frame.point_to_pixel(seed.x, seed.y)
            pixel, dist = _snap_seed(
                col, row, working, frame, cfg.sea.seed_snap_radius
            )
            if pixel is None:
                if zone.retired:
                    # 1.9: a retired zone needs no reachable seed.
                    continue
                errors.append(
                    PipelineError(
                        SEED_OUTSIDE_WATER,
                        f"zone {zone.key!r}: seed ({seed.x}, {seed.y}) has "
                        f"no working-water pixel within "
                        f"{cfg.sea.seed_snap_radius} units",
                    )
                )
                continue
            claimed = bool(labels[pixel[1], pixel[0]] != 0)
            snapped.append(
                SnappedSeed(
                    zone_key=zone.key,
                    point=(seed.x, seed.y),
                    pixel=pixel,
                    distance=dist,
                    claimed=claimed,
                )
            )
            if claimed:
                continue
            labels[pixel[1], pixel[0]] = z
            queue.append(pixel[1] * w + pixel[0])
    return labels, queue, snapped, errors


def _grow_labels(labels: np.ndarray, working: np.ndarray,
                 queue: list[int]) -> None:
    """Propagate seed labels through working water W'.

    A W' component whose seeds all belong to one zone is labelled wholesale
    (the BFS could only reach that result anyway); components seeded by
    several zones get a real multi-source BFS, queued in global seed order.
    """
    h, w = working.shape
    comp, _ = ndimage.label(working, structure=_CROSS)
    flat_labels = labels.ravel()
    flat_comp = comp.ravel()

    comp_zones: dict[int, set[int]] = {}
    for pos in queue:
        comp_zones.setdefault(int(flat_comp[pos]), set()).add(
            int(flat_labels[pos])
        )

    multi = np.zeros(working.size, dtype=bool)
    for cid in sorted(comp_zones):
        zones = comp_zones[cid]
        if len(zones) == 1:
            flat_labels[flat_comp == cid] = next(iter(zones))
        else:
            multi[flat_comp == cid] = True

    bfs_queue = [pos for pos in queue if multi[pos]]
    if not bfs_queue:
        return

    flat_working = working.ravel()
    dq = deque(bfs_queue)
    while dq:
        pos = dq.popleft()
        row, col = divmod(pos, w)
        z = flat_labels[pos]
        for dx, dy in _NEIGHBOURS:
            nc, nr = col + dx, row + dy
            if nc < 0 or nc >= w or nr < 0 or nr >= h:
                continue
            npos = nr * w + nc
            if flat_working[npos] and flat_labels[npos] == 0:
                flat_labels[npos] = z
                dq.append(npos)


def _component_centroid(center_rc: tuple[float, float],
                        frame: RasterFrame) -> tuple[float, float]:
    row, col = center_rc
    return (frame.x0 + col / frame.r, frame.y0 + row / frame.r)


def _describe(mask_slices: tuple, centroid: tuple[float, float],
              area: float, frame: RasterFrame) -> str:
    rows, cols = mask_slices
    cx, cy = centroid
    return (
        f"area={round(area, 2)} centroid=({round(cx, 2)}, {round(cy, 2)}) "
        f"bbox=({round(frame.x0 + cols.start / frame.r, 2)}, "
        f"{round(frame.y0 + rows.start / frame.r, 2)})..("
        f"{round(frame.x0 + (cols.stop - 1) / frame.r, 2)}, "
        f"{round(frame.y0 + (rows.stop - 1) / frame.r, 2)})"
    )


def build_seas(
    nodes,
    geoms: dict[str, list[Polygon]],
    overrides: Overrides,
    cfg: PipelineConfig,
) -> SeaRaster:
    """Build the sea raster; raise ``PipelineFailure`` on any defect.

    Every independent error (bad seeds, empty zones, unseeded water bodies,
    invalid ``water_outside`` points, oversized unreached band pieces) is
    collected before the failure is raised.
    """
    r = cfg.raster.pixels_per_unit
    eps = cfg.geometry.border_epsilon
    frame = _compute_frame(nodes, overrides, r)

    tech_exclude = set(overrides.technical_exclude)
    frame_box = box(frame.x0, frame.y0, frame.x1, frame.y1)
    land_parts = [
        p
        for name in sorted(geoms)
        if name.lower() not in tech_exclude
        for p in geoms[name]
        if p.intersects(frame_box)
    ]
    land = mask_from_geometry(_union_closed(land_parts, eps), frame)
    water = ~land

    playable_parts = [p for n in nodes.values() for p in n.parts]
    playable = mask_from_geometry(_union_closed(playable_parts, eps), frame)

    band = _compute_band(playable, overrides, r)
    working = water & band

    labels, queue, snapped, errors = _place_seeds(
        overrides, working, frame, cfg
    )
    _grow_labels(labels, working, queue)

    # Water classification over the full frame water (before band clipping).
    wcomp, ncomp = ndimage.label(water, structure=_CROSS)
    comp_area = np.bincount(wcomp.ravel(), minlength=ncomp + 1) / (r * r)
    comp_slices = ndimage.find_objects(wcomp)
    comp_centers = (
        ndimage.center_of_mass(water, wcomp, np.arange(1, ncomp + 1))
        if ncomp
        else []
    )
    seeded_comps = {
        int(wcomp[s.pixel[1], s.pixel[0]])
        for s in snapped
        if not s.claimed
    }
    touches_band = np.zeros(ncomp + 1, dtype=bool)
    band_comps = np.unique(wcomp[band])
    touches_band[band_comps[band_comps > 0]] = True

    # water_outside validation: pixel in W; component unseeded and large.
    outside_pts: list[tuple[str, int]] = []  # (name, component id)
    outside_comps: set[int] = set()
    for entry in overrides.water_outside:
        col, row = frame.point_to_pixel(entry.point.x, entry.point.y)
        cid = 0
        if 0 <= col < frame.width and 0 <= row < frame.height:
            cid = int(wcomp[row, col])
        if (
            cid == 0
            or cid in seeded_comps
            or comp_area[cid] < overrides.lake_max_area
        ):
            errors.append(
                PipelineError(
                    WATER_OUTSIDE_INVALID,
                    f"water_outside {entry.name!r} point "
                    f"({entry.point.x}, {entry.point.y}) is not inside an "
                    "unseeded water body of at least "
                    f"{overrides.lake_max_area} sq. units",
                )
            )
            continue
        outside_pts.append((entry.name, cid))
        outside_comps.add(cid)

    # Per-component kind lookup: 0 land, 1 zone water (labelled W' pixels
    # only), 2 unknown sea, 3 lake. Water beyond the band stays unknown sea
    # even inside a seeded body.
    kind_lut = np.zeros(ncomp + 1, dtype=np.uint8)
    kind_lut[1:] = KIND_UNKNOWN_SEA
    lakes: list[Lake] = []
    for cid in range(1, ncomp + 1):
        if cid in seeded_comps:
            pass  # zone water, marked per-pixel via `labels` below
        elif comp_area[cid] < overrides.lake_max_area:
            kind_lut[cid] = KIND_LAKE
            lakes.append(
                Lake(
                    area=float(comp_area[cid]),
                    centroid=_component_centroid(
                        comp_centers[cid - 1], frame
                    ),
                )
            )
        elif touches_band[cid] and cid not in outside_comps:
            # Ignored far water and outside water stay unknown sea.
            errors.append(
                PipelineError(
                    UNSEEDED_WATER,
                    "unseeded water body: "
                    + _describe(
                        comp_slices[cid - 1],
                        _component_centroid(comp_centers[cid - 1], frame),
                        float(comp_area[cid]),
                        frame,
                    ),
                )
            )
    kinds = kind_lut[wcomp]
    kinds[labels > 0] = KIND_ZONE_WATER
    retired = frozenset(z.key for z in overrides.sea_zones if z.retired)
    if retired:
        # Retired zones still hold their labels (their water is not given
        # to the neighbours) but the pixels render as unexplored sea.
        retired_idx = [
            i + 1
            for i, z in enumerate(overrides.sea_zones)
            if z.retired
        ]
        kinds[np.isin(labels, retired_idx)] = KIND_UNKNOWN_SEA

    # Unreached pieces of seeded water bodies (band parts without a seed):
    # a W' component carries no label iff none of its pixels was seeded.
    wprime, nwprime = ndimage.label(working, structure=_CROSS)
    wprime_slices = ndimage.find_objects(wprime)
    index = np.arange(1, nwprime + 1)
    reached = (
        ndimage.maximum(labels, wprime, index) if nwprime else []
    )
    parent = (
        ndimage.maximum(wcomp.astype(np.int32), wprime, index)
        if nwprime
        else []
    )
    wprime_count = np.bincount(wprime.ravel(), minlength=nwprime + 1)
    unreached_small_count = 0
    unreached_small_area = 0.0
    for cid in range(1, nwprime + 1):
        if reached[cid - 1] > 0 or int(parent[cid - 1]) not in seeded_comps:
            continue
        area = float(wprime_count[cid]) / (r * r)
        if area < overrides.lake_max_area:
            unreached_small_count += 1
            unreached_small_area += area
            continue
        rows, cols = wprime_slices[cid - 1]
        m = wprime == cid
        rc = ndimage.center_of_mass(m)
        errors.append(
            PipelineError(
                UNSEEDED_WATER,
                "unreached band piece inside a seeded water body: "
                + _describe(
                    (rows, cols),
                    _component_centroid(rc, frame),
                    area,
                    frame,
                ),
            )
        )

    zone_areas = [
        float((labels == z).sum()) / (r * r)
        for z in range(1, len(overrides.sea_zones) + 1)
    ]
    for z, zone in enumerate(overrides.sea_zones, start=1):
        if zone.retired:
            continue
        if zone_areas[z - 1] == 0:
            errors.append(
                PipelineError(
                    ZONE_EMPTY, f"zone {zone.key!r} received no pixels"
                )
            )

    if errors:
        raise PipelineFailure(errors)

    return SeaRaster(
        frame=frame,
        zone_keys=[z.key for z in overrides.sea_zones],
        zone_name_ru=[z.name_ru for z in overrides.sea_zones],
        water=water,
        band=band,
        working=working,
        land=land,
        playable=playable,
        labels=labels,
        kinds=kinds,
        zone_areas=zone_areas,
        retired=retired,
        snapped=snapped,
        lakes=lakes,
        water_outside=[
            (name, float(comp_area[cid])) for name, cid in outside_pts
        ],
        unreached_small_count=unreached_small_count,
        unreached_small_area=unreached_small_area,
    )


def land_label_raster(
    ordered_nodes: list,  # nodes sorted by id, each with .parts
    land: np.ndarray,
    frame: RasterFrame,
) -> np.ndarray:
    """Draw each included node's parts as its 1-based index, then mask by L.

    Nodes are drawn in ascending id order (later draws overwrite earlier);
    pixels of excluded land and dropped parts keep label 0.
    """
    img = Image.new("I", (frame.width, frame.height), 0)
    draw = ImageDraw.Draw(img)
    for idx, node in enumerate(ordered_nodes, start=1):
        for part in node.parts:
            fill_polygon(draw, part, idx, frame)
    labels = np.array(img, dtype=np.int32)
    labels[~land] = 0
    return labels
