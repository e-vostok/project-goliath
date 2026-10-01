"""PNG preview of the node graph (Appendix A step 6 output).

Rendered at ``preview.pixels_per_unit`` over the raster frame: unknown sea
dark blue-grey, each zone a deterministic pastel colour with its index
number, lakes light blue, included land light grey with darker province
outlines, excluded/dropped land mid-grey, straits red, and land nodes with
no edges red (should not occur).
"""
from __future__ import annotations

import colorsys

import numpy as np
from PIL import Image, ImageDraw

from .graph import Graph
from .pipeline_config_schema import PipelineConfig
from .seas import KIND_LAKE, KIND_UNKNOWN_SEA, KIND_ZONE_WATER, SeaRaster

_UNKNOWN_SEA = (46, 60, 74)
_LAKE = (150, 190, 225)
_LAND = (210, 210, 210)
_LAND_EXCLUDED = (140, 140, 140)
_OUTLINE = (90, 90, 90)
_STRAIT = (220, 40, 40)
_ISOLATED = (220, 40, 40)
_TEXT = (20, 20, 20)


def _zone_color(index: int) -> tuple[int, int, int]:
    """Deterministic pastel for 1-based zone index (golden-ratio hue)."""
    r, g, b = colorsys.hsv_to_rgb((index * 0.6180339887) % 1.0, 0.35, 0.88)
    return (round(r * 255), round(g * 255), round(b * 255))


def _zone_label_pixel(labels: np.ndarray, zone: int) -> tuple[float, float]:
    """Zone pixel nearest the zone's centroid: (col, row)."""
    rows, cols = np.nonzero(labels == zone)
    mc, mr = cols.mean(), rows.mean()
    i = int(np.argmin((cols - mc) ** 2 + (rows - mr) ** 2))
    return float(cols[i]), float(rows[i])


def render_preview(
    sea: SeaRaster,
    land_labels: np.ndarray,
    graph: Graph,
    land_parts: dict[str, list],
    cfg: PipelineConfig,
) -> Image.Image:
    """Render the preview image; does not write any file."""
    frame = sea.frame
    ppu = cfg.preview.pixels_per_unit
    scale = ppu / frame.r
    out_w = max(1, round(frame.width * scale))
    out_h = max(1, round(frame.height * scale))

    base = np.zeros((frame.height, frame.width, 3), dtype=np.uint8)
    base[sea.kinds == KIND_UNKNOWN_SEA] = _UNKNOWN_SEA
    base[sea.kinds == KIND_LAKE] = _LAKE
    base[sea.land] = _LAND_EXCLUDED
    base[land_labels > 0] = _LAND
    for z in range(1, len(sea.zone_keys) + 1):
        base[sea.labels == z] = _zone_color(z)

    img = Image.fromarray(base).resize((out_w, out_h), Image.NEAREST)
    draw = ImageDraw.Draw(img)

    def px(x: float, y: float) -> tuple[float, float]:
        return ((x - frame.x0) * ppu, (y - frame.y0) * ppu)

    degree = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        degree[e.a] += 1
        degree[e.b] += 1
    by_id = {n.id: n for n in graph.nodes}
    by_key = {n.key: n for n in graph.nodes}

    # province outlines over the resized raster
    for key in sorted(land_parts):
        node = by_key.get(key)
        fill = _ISOLATED if node is not None and degree[node.id] == 0 else None
        for part in land_parts[key]:
            ring = [px(x, y) for x, y in part.exterior.coords]
            draw.polygon(ring, fill=fill, outline=_OUTLINE)

    for e in graph.edges:
        if e.type != "strait":
            continue
        pa = by_id[e.a].geom.representative_point()
        pb = by_id[e.b].geom.representative_point()
        draw.line([px(pa.x, pa.y), px(pb.x, pb.y)], fill=_STRAIT, width=2)

    for z in range(1, len(sea.zone_keys) + 1):
        col, row = _zone_label_pixel(sea.labels, z)
        draw.text((col * scale, row * scale), str(z), fill=_TEXT)

    return img
