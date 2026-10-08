"""Tiny crop renderer for the map2_9 diagnosis pictures (Pillow).

Draws a window of the map in view-box units: sea zones, land node outlines,
graph edges (as anchor-to-anchor lines, like ``preview.py``) and optional
highlight rings/labels. 40 px per unit is the default scale.
"""
from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon
from PIL import Image, ImageDraw, ImageFont

SEA_FILL = (30, 53, 71)
LAND_FILL = (140, 140, 140)
LAND_BORDER = (58, 58, 58)
OUTSIDE = (26, 26, 26)
STRAIT = (220, 40, 40)
LAND_EDGE = (90, 90, 90)
SEA_EDGE = (70, 110, 160)
COAST_EDGE = (60, 80, 100)
SELECT = (255, 210, 74)

RING_COLORS = [
    (255, 99, 71),
    (80, 170, 255),
    (150, 230, 120),
    (230, 160, 255),
    (255, 200, 90),
    (90, 230, 210),
    (255, 140, 180),
    (190, 190, 90),
]


def _iter_polys(geom):
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms


def render_crop(
    out_path,
    bbox,
    land_geoms: dict[int, object],
    sea_geoms: dict[int, object],
    nodes: dict[int, dict],
    edges: list[dict],
    scale: float = 40.0,
    highlight: dict[int, str] | None = None,
    ring_colors_for: set[int] | None = None,
    label_ids: set[int] | None = None,
    margin_u: float = 0.6,
    vertex_dots_for: set[int] | None = None,
):
    x0, y0, x1, y1 = bbox
    x0 -= margin_u
    y0 -= margin_u
    x1 += margin_u
    y1 += margin_u
    w = max(2, int((x1 - x0) * scale))
    h = max(2, int((y1 - y0) * scale))
    img = Image.new("RGB", (w, h), OUTSIDE)
    dr = ImageDraw.Draw(img)

    def px(x, y):
        return ((x - x0) * scale, (y - y0) * scale)

    def ring(coords):
        return [px(x, y) for x, y in coords]

    # sea first, land on top
    for geom in sea_geoms.values():
        for poly in _iter_polys(geom):
            dr.polygon(ring(poly.exterior.coords), fill=SEA_FILL)
            for hole in poly.interiors:
                dr.polygon(ring(hole.coords), fill=OUTSIDE)
    for nid, geom in land_geoms.items():
        for poly in _iter_polys(geom):
            ext = ring(poly.exterior.coords)
            dr.polygon(ext, fill=LAND_FILL, outline=LAND_BORDER)
            for hole in poly.interiors:
                dr.polygon(ring(hole.coords), fill=SEA_FILL)

    # edges as anchor-to-anchor lines
    for e in edges:
        na, nb = nodes.get(e["a"]), nodes.get(e["b"])
        if na is None or nb is None:
            continue
        pa = px(*na["anchor"])
        pb = px(*nb["anchor"])
        if e["type"] == "strait":
            dr.line([pa, pb], fill=STRAIT, width=3)
        elif e["type"] == "land":
            dr.line([pa, pb], fill=LAND_EDGE, width=1)
        elif e["type"] == "sea":
            dr.line([pa, pb], fill=SEA_EDGE, width=1)
        else:
            dr.line([pa, pb], fill=COAST_EDGE, width=1)

    # highlights / per-ring colours
    ring_colors_for = ring_colors_for or set()
    vertex_dots_for = vertex_dots_for or set()
    for nid, colour in (highlight or {}).items():
        for poly in _iter_polys(land_geoms.get(nid) or []):
            coords = ring(poly.exterior.coords)
            dr.line(coords + [coords[0]], fill=colour, width=3)
    for nid in ring_colors_for:
        parts = list(_iter_polys(land_geoms[nid]))
        parts.sort(key=lambda p: -p.area)
        for i, poly in enumerate(parts):
            c = RING_COLORS[i % len(RING_COLORS)]
            coords = ring(poly.exterior.coords)
            dr.line(coords + [coords[0]], fill=c, width=2)
            if nid in vertex_dots_for:
                r = max(2.0, scale * 0.06)
                for x, y in coords:
                    dr.ellipse([x - r, y - r, x + r, y + r], fill=c)

    if label_ids:
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except OSError:
            font = ImageFont.load_default()
        for nid in label_ids:
            n = nodes[nid]
            x, y = px(*n["anchor"])
            dr.text((x + 3, y - 8), f"{n['key']} ({n.get('name_ru') or ''})",
                    fill=(255, 255, 255), font=font)

    img.save(out_path)
    return img.size
