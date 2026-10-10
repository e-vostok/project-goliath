"""PNG crops of the canonical borders at 40 px/unit (PIL).

Fills use pastel demo-state colours; internal borders (same state) are
dashed, borders between different owners solid and thicker, coast thin
dark. This mirrors the requested preview styles.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 40.0  # px per map unit
COL_SEA = (30, 53, 71)       # colors.sea
COL_OUTSIDE = (42, 42, 42)   # colors.outside
COL_FREE = (140, 140, 140)   # colors.neutral_province
COL_INTERNAL = (35, 35, 38)
COL_EXTERNAL = (12, 12, 14)
COL_COAST = (22, 26, 30)

W_IN = 1.0     # internal dashed border, px
W_OUT = 2.2    # state border, px
W_COAST = 1.2  # coast, px
DASH, GAP = 5.0, 3.5


def state_color(i: int) -> tuple[int, int, int]:
    """Deterministic pastel from the golden-ratio hue sequence."""
    import colorsys

    h = (i * 0.61803398875) % 1.0
    r, g, b = colorsys.hls_to_rgb(h, 0.72, 0.45)
    return int(r * 255), int(g * 255), int(b * 255)


def _polys(geom):
    """World-coord exterior rings with holes for PIL polygon fill."""
    parts = geom.geoms if hasattr(geom, "geoms") else [geom]
    out = []
    for p in parts:
        out.append(
            (list(p.exterior.coords), [list(r.coords) for r in p.interiors])
        )
    return out


def _fill_part(draw, ext, holes, box, fill):
    def tx(coords):
        return [
            ((x - box[0]) * S, (y - box[1]) * S) for x, y in coords
        ]

    draw.polygon(tx(ext), fill=fill)
    for hole in holes:
        draw.polygon(tx(hole), fill=COL_SEA)


def _dash_line(draw, pts, box, dash, gap, fill, width):
    acc = -gap  # start in the "on" phase
    on = True
    for a, b in zip(pts, pts[1:]):
        ax, ay = (a[0] - box[0]) * S, (a[1] - box[1]) * S
        bx, by = (b[0] - box[0]) * S, (b[1] - box[1]) * S
        seg = math.hypot(bx - ax, by - ay)
        t = 0.0
        while t < seg:
            want = dash if on else gap
            step = min(want - acc, seg - t)
            if on:
                f = t / seg
                g = (t + step) / seg
                draw.line(
                    [
                        ax + (bx - ax) * f, ay + (by - ay) * f,
                        ax + (bx - ax) * g, ay + (by - ay) * g,
                    ],
                    fill=fill,
                    width=max(1, round(width)),
                )
            t += step
            acc += step
            if acc >= want - 1e-9:
                acc = 0.0
                on = not on


def _solid_line(draw, pts, box, fill, width):
    xy = [((x - box[0]) * S, (y - box[1]) * S) for x, y in pts]
    if len(xy) >= 2:
        draw.line(xy, fill=fill, width=max(1, round(width)), joint="curve")


def render_crop(
    path: Path,
    box: tuple[float, float, float, float],
    nodes: dict,
    border_map: dict,
    coast_arcs: dict,
    state: dict,
    outside_parts=None,
) -> int:
    w = round((box[2] - box[0]) * S)
    h = round((box[3] - box[1]) * S)
    img = Image.new("RGB", (w, h), COL_SEA)
    draw = ImageDraw.Draw(img, "RGBA")

    if outside_parts:
        for ext, holes in outside_parts:
            _fill_part(draw, ext, holes, box, COL_OUTSIDE)

    for nid, node in nodes.items():
        if node.geom.bounds[2] < box[0] or node.geom.bounds[0] > box[2]:
            continue
        if node.geom.bounds[3] < box[1] or node.geom.bounds[1] > box[3]:
            continue
        col = COL_FREE if state.get(nid, -1) < 0 else state_color(
            state[nid]
        )
        for ext, holes in _polys(node.geom):
            _fill_part(draw, ext, holes, box, col)

    # canonical borders: dashed inside one state, solid between owners
    for (a, b), arcs in border_map.items():
        internal = state.get(a, -1) == state.get(b, -2) and state.get(
            a, -1
        ) >= 0
        for arc in arcs:
            if internal:
                _dash_line(draw, arc.pts, box, DASH, GAP, COL_INTERNAL, W_IN)
            else:
                _solid_line(draw, arc.pts, box, COL_EXTERNAL, W_OUT)

    for nid, arcs in coast_arcs.items():
        for arc in arcs:
            pts = arc.pts + ([arc.pts[0]] if arc.closed else [])
            _solid_line(draw, pts, box, COL_COAST, W_COAST)

    img.save(path, optimize=True)
    return path.stat().st_size


def render_crops(
    ref_dir: Path, manifest, nodes, border_map, coast_arcs, state,
    method: str, crops: dict,
) -> dict:
    sizes = {}
    for name, box in crops.items():
        path = ref_dir / f"borders_crop_{name}.png"
        sizes[name] = render_crop(
            path, box, nodes, border_map, coast_arcs, state
        )
    return sizes
