"""map2_2 Phase A: the drawing canvas for a province split.

    python -m tools.map_pipeline.make_split_canvas <key>

Renders the area around one LAND node of ``data/map/`` into
``tools/map_pipeline/reference/<key>_split_canvas.png`` plus a
``<key>_split_canvas.registration.json`` that maps image pixels back to
base coordinates (``pixel = (x - origin_x) * px_per_unit``, y down — the
same convention as ``boundary_v2_markup.registration.json``).

The picture uses the game's own palette and layer order
(``preview.render_map_preview``): sea dark blue, ``outside`` dark grey,
playable land mid-grey, thin dark outlines. The target province is
re-filled in a light colour, land neighbours carry their ``name`` labels,
a 1-unit grid with margin labels helps placement, and the node's current
``anchor`` is marked — the half that contains it keeps the old key/id.

The Project Owner draws the dividing line on this file in pure red
(255, 0, 0); the script refuses to write a canvas that already contains
that colour, so the markup pass in Phase B can rely on the colour being
unclaimed. No file under ``data/`` is touched.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Point, box

from .errors import DATA_INVALID, PipelineError, print_errors
from .pipeline_config_schema import load_pipeline_config
from .preview import _rgb, _stamp, render_map_preview
from .svgpath import parse_path

MARKUP_RED = (255, 0, 0)

# Crop and output sizing (map2_2 spec): pad the target bbox on every side,
# then scale so the longer image side is about this many pixels.
PAD_UNITS = 3.0
TARGET_LONG_SIDE = 2800

# Canvas-only palette on top of the game render.
_TARGET_FILL = (216, 212, 196)     # light, clearly not an owner colour
_GRID = (255, 255, 255, 45)        # soft white grid over everything
_LABEL = (245, 245, 238)
_LABEL_STROKE = (15, 15, 15)
_TARGET_LABEL = (30, 30, 30)
_TARGET_LABEL_STROKE = (240, 240, 235)
_ANCHOR = (255, 176, 0)            # orange marker, far from markup red

_LABEL_MIN_PPU = 40.0  # below this, margin labels switch to every 5 units


def _node_by_key(manifest: dict, key: str) -> dict:
    node = next(
        (n for n in manifest["nodes"] if n["key"] == key), None
    )
    if node is None:
        raise PipelineError(
            DATA_INVALID, f"no node with key {key!r} in manifest.json"
        )
    if node["kind"] != "LAND":
        raise PipelineError(
            DATA_INVALID, f"node {key!r} is {node['kind']}, not LAND"
        )
    return node


def _label_font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=px)


def _label_point(parts, crop: box):
    """A point safely inside the clipped node geometry, for its label."""
    clipped = [p.intersection(crop) for p in parts]
    clipped = [g for g in clipped if not g.is_empty]
    if not clipped:
        return None
    biggest = max(clipped, key=lambda g: g.area)
    return biggest.representative_point()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    pos: tuple[float, float],
    text: str,
    font,
    fill,
    stroke_fill,
    origin: tuple[float, float],
    ppu: float,
) -> None:
    ox, oy = origin
    draw.text(
        ((pos[0] - ox) * ppu, (pos[1] - oy) * ppu),
        text,
        font=font,
        fill=fill,
        anchor="mm",
        stroke_width=max(1, font.size // 8),
        stroke_fill=stroke_fill,
    )


def _draw_grid(
    img: Image.Image,
    crop: tuple[float, float, float, float],
    ppu: float,
    font,
) -> None:
    """1-unit grid plus coordinate labels along the top and left edges."""
    x0, y0, x1, y1 = crop
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for gx in range(int(np.ceil(x0)), int(np.floor(x1)) + 1):
        px = (gx - x0) * ppu
        od.line([(px, 0), (px, img.height)], fill=_GRID)
    for gy in range(int(np.ceil(y0)), int(np.floor(y1)) + 1):
        py = (gy - y0) * ppu
        od.line([(0, py), (img.width, py)], fill=_GRID)
    img.alpha_composite(overlay)

    draw = ImageDraw.Draw(img)
    step = 1 if ppu >= _LABEL_MIN_PPU else 5
    for gx in range(int(np.ceil(x0)), int(np.floor(x1)) + 1):
        if gx % step:
            continue
        draw.text(
            ((gx - x0) * ppu + 2, 1),
            str(gx),
            font=font,
            fill=_LABEL,
            stroke_width=max(1, font.size // 8),
            stroke_fill=_LABEL_STROKE,
        )
    for gy in range(int(np.ceil(y0)), int(np.floor(y1)) + 1):
        if gy % step:
            continue
        draw.text(
            (2, (gy - y0) * ppu + 1),
            str(gy),
            font=font,
            fill=_LABEL,
            stroke_width=max(1, font.size // 8),
            stroke_fill=_LABEL_STROKE,
        )


def render_canvas(
    manifest: dict,
    geometry: dict,
    key: str,
    crop: tuple[float, float, float, float],
    ppu: float,
    colors,
) -> tuple[Image.Image, dict]:
    """The marked-up canvas image; pure building block for tests/Phase B."""
    paths = {k: parse_path(d) for k, d in geometry["paths"].items()}
    outside_parts = parse_path(geometry["outside"])
    sea_water_d = geometry.get("sea_water") or ""
    sea_water_parts = parse_path(sea_water_d) if sea_water_d else []
    sea_ids = {
        str(n["id"]) for n in manifest["nodes"] if n["kind"] == "SEA"
    }
    img = render_map_preview(
        paths, outside_parts, crop, ppu, colors, sea_ids, sea_water_parts
    ).convert("RGBA")

    origin = (crop[0], crop[1])
    node = _node_by_key(manifest, key)
    target_parts = paths[str(node["id"])]
    _stamp(
        img, target_parts, origin, ppu, _TARGET_FILL,
        outline=_rgb(colors.border),
    )

    crop_box = box(*crop)
    by_id = {n["id"]: n for n in manifest["nodes"]}
    neighbours = {
        e["a"] if e["b"] == node["id"] else e["b"]
        for e in manifest["edges"]
        if node["id"] in (e["a"], e["b"])
        and e["type"] in ("land", "strait")
    }
    font = _label_font(max(14, round(ppu * 0.22)))
    draw = ImageDraw.Draw(img)

    # Land neighbours (always) and any other land node whose anchor lies
    # inside the crop get their ``name`` at a point inside the visible part.
    labelled: set[int] = set()
    for n in manifest["nodes"]:
        if n["kind"] != "LAND" or n["id"] == node["id"]:
            continue
        anchor_in = crop_box.covers(Point(*n["anchor"]))
        if n["id"] not in neighbours and not anchor_in:
            continue
        pos = _label_point(paths[str(n["id"])], crop_box)
        if pos is None:
            continue
        _draw_label(
            draw, (pos.x, pos.y), n["name"], font,
            _LABEL, _LABEL_STROKE, origin, ppu,
        )
        labelled.add(n["id"])

    # The target itself: name plus the current anchor marker (that half
    # keeps the old key/id by default).
    ax, ay = node["anchor"]
    px, py = (ax - origin[0]) * ppu, (ay - origin[1]) * ppu
    r = max(3.0, ppu * 0.06)
    draw.ellipse(
        [px - r, py - r, px + r, py + r],
        fill=_ANCHOR,
        outline=_LABEL_STROKE,
        width=2,
    )
    big = _label_font(max(18, round(ppu * 0.3)))
    _draw_label(
        draw, (ax, ay - 0.5), node["name"], big,
        _TARGET_LABEL, _TARGET_LABEL_STROKE, origin, ppu,
    )

    _draw_grid(img, crop, ppu, _label_font(max(12, round(ppu * 0.14))))
    return img, node


def run(data_dir: Path, key: str, out_dir: Path) -> dict:
    """Write the canvas + registration files; returns report facts."""
    manifest = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    geometry = json.loads(
        (data_dir / "geometry.json").read_text(encoding="utf-8")
    )
    node = _node_by_key(manifest, key)

    x0, y0, x1, y1 = node["bbox"]
    crop = (x0 - PAD_UNITS, y0 - PAD_UNITS, x1 + PAD_UNITS, y1 + PAD_UNITS)
    w_u, h_u = crop[2] - crop[0], crop[3] - crop[1]
    ppu = TARGET_LONG_SIDE / max(w_u, h_u)
    width = max(1, round(w_u * ppu))
    height = max(1, round(h_u * ppu))

    cfg = load_pipeline_config()
    img, node = render_canvas(
        manifest, geometry, key, crop, ppu, cfg.preview.colors
    )
    img = img.convert("RGB")

    rgb = np.asarray(img, dtype=np.uint8)
    if int(((rgb == MARKUP_RED).all(-1)).sum()):
        raise PipelineError(
            DATA_INVALID,
            "canvas already contains pure red (255,0,0) — the markup "
            "colour must stay unclaimed",
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{key}_split_canvas.png"
    reg_path = out_dir / f"{key}_split_canvas.registration.json"
    img.save(png_path)
    reg = {
        "key": key,
        "image": png_path.name,
        "image_size": [width, height],
        "px_per_unit": round(ppu, 6),
        "origin_x": round(crop[0], 4),
        "origin_y": round(crop[1], 4),
        "width": width,
        "height": height,
        "_comment": (
            "base -> px: px = (base - origin) * px_per_unit (y down, same "
            "orientation as the base space). "
            "px -> base: base = origin + px / px_per_unit. "
            "origin = the crop corner in base coordinates "
            "(units of manifest.view_box)."
        ),
    }
    reg_path.write_text(
        json.dumps(reg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "png": png_path,
        "registration": reg_path,
        "px_per_unit": ppu,
        "size": (width, height),
        "crop_units": (w_u, h_u),
        "crop_origin": (crop[0], crop[1]),
        "node": node,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.map_pipeline.make_split_canvas",
        description="Draw the Phase A markup canvas for splitting "
        "one LAND node in two.",
    )
    parser.add_argument("key", help="node key, e.g. alexandria")
    parser.add_argument("--data-dir", default="data/map", type=Path)
    parser.add_argument(
        "--out-dir",
        default=Path("tools/map_pipeline/reference"),
        type=Path,
    )
    args = parser.parse_args(argv)
    try:
        info = run(args.data_dir, args.key, args.out_dir)
    except PipelineError as err:
        print_errors([err])
        return 1
    w, h = info["size"]
    wu, hu = info["crop_units"]
    node = info["node"]
    print(f"{info['png']} ({w}x{h} px)")
    print(f"{info['registration']}")
    print(
        f"scale {info['px_per_unit']:.2f} px/unit; "
        f"area {wu:.2f} x {hu:.2f} units at "
        f"({info['crop_origin'][0]:.2f}, {info['crop_origin'][1]:.2f})"
    )
    print(
        f"{node['key']}: id {node['id']}, current area {node['area']}, "
        f"anchor ({node['anchor'][0]}, {node['anchor'][1]}) "
        "— orange dot; that half keeps the old key by default"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
