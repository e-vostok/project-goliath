"""PNG preview of the node graph (Appendix A step 6 output).

Rendered at ``preview.pixels_per_unit`` over the raster frame: unknown sea
dark blue-grey, each zone a deterministic pastel colour with its index
number, lakes light blue, included land light grey with darker province
outlines, excluded/dropped land mid-grey, straits red, and land nodes with
no edges red (should not occur).
"""
from __future__ import annotations

import colorsys
import math

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


# ------------------------------------------------------------------- MP-3


def _rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def _stamp(img: Image.Image, polys, origin, ppu, fill, outline=None):
    """Paint polygons through a mask so their holes stay transparent.

    Each part's mask is cropped to its pixel bbox; outlines are drawn as
    1 px lines on top of the fill.
    """
    ox, oy = origin
    w_img, h_img = img.size
    draw = ImageDraw.Draw(img)
    for poly in polys:
        bx0, by0, bx1, by1 = poly.bounds
        x0 = max(0, math.floor((bx0 - ox) * ppu) - 1)
        y0 = max(0, math.floor((by0 - oy) * ppu) - 1)
        x1 = min(w_img, math.ceil((bx1 - ox) * ppu) + 1)
        y1 = min(h_img, math.ceil((by1 - oy) * ppu) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        md = ImageDraw.Draw(mask)

        def mask_coords(ring):
            return [
                ((x - ox) * ppu - x0, (y - oy) * ppu - y0)
                for x, y in ring.coords
            ]

        def img_coords(ring):
            return [
                ((x - ox) * ppu, (y - oy) * ppu) for x, y in ring.coords
            ]

        md.polygon(mask_coords(poly.exterior), fill=255)
        for hole in poly.interiors:
            md.polygon(mask_coords(hole), fill=0)
        img.paste(fill, (x0, y0), mask)
        if outline is not None:
            draw.line(img_coords(poly.exterior), fill=outline, width=1,
                      joint="curve")
            for hole in poly.interiors:
                draw.line(img_coords(hole), fill=outline, width=1,
                          joint="curve")


def render_map_preview(
    paths: dict[str, list],
    outside_parts: list,
    window: tuple[float, float, float, float],
    ppu: int,
    colors,
    sea_ids: set[str] | None = None,
) -> Image.Image:
    """Render parsed ``geometry.json`` over ``window`` at ``ppu``.

    Layer order (Spec MapView): ``inland_water`` background, ``outside``,
    sea zones (``sea`` fill, ``sea_border`` outline), land nodes (``land``
    fill, ``border`` outline).
    """
    x0, y0, x1, y1 = window
    w = max(1, round((x1 - x0) * ppu))
    h = max(1, round((y1 - y0) * ppu))
    img = Image.new("RGB", (w, h), _rgb(colors.inland_water))
    _stamp(img, outside_parts, (x0, y0), ppu, _rgb(colors.outside))
    seas = [
        p for k in sorted(paths) if sea_ids and k in sea_ids
        for p in paths[k]
    ]
    lands = [
        p for k in sorted(paths) if not sea_ids or k not in sea_ids
        for p in paths[k]
    ]
    _stamp(img, seas, (x0, y0), ppu, _rgb(colors.sea),
           outline=_rgb(colors.sea_border))
    _stamp(img, lands, (x0, y0), ppu, _rgb(colors.land),
           outline=_rgb(colors.border))
    return img
