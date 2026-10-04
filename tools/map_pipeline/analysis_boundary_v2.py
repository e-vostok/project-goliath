"""map_polish_2 Phase A — analysis of the boundary_v2 markup image.

Reads ``reference/boundary_v2_markup.png`` plus its registration, computes
the red-pixel fraction of every ``boundary.yaml`` include province, checks
nodes against ``view.frame``, reports sea-zone facts and predicts the side
effects of the proposed exclusions. Writes NOTHING to ``data/``; images go
to ``tools/map_pipeline/reference/``, numeric dumps to
``tools/map_pipeline/out/analysis/``.
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw
from scipy import ndimage

from .errors import PipelineFailure
from .models import (
    Boundary,
    Overrides,
    load_boundary,
    load_ids_lock,
    load_overrides,
)
from .pipeline_config_schema import load_pipeline_config
from .seas import _CROSS
from .svg_source import build_geometries, read_province_paths

DATA = Path("data/map")
REF = Path("tools/map_pipeline/reference")
OUT = Path("tools/map_pipeline/out/analysis")

RED_EXCLUDE = 0.50
RED_UNCERTAIN = 0.15
DECIDED_EXCLUDE = {"Canary_Islands"}  # Project Owner decision 04.10.2026


def load_geoms(data_dir: Path, cfg):
    """Source-name -> parts, cached in out/ (keyed by svg mtime)."""
    svg = data_dir / "source/map.svg"
    cache = OUT / "_geoms.pkl"
    stamp = svg.stat().st_mtime_ns
    paths = read_province_paths(svg)
    if cache.exists():
        try:
            saved = pickle.loads(cache.read_bytes())
            if saved[0] == stamp:
                return paths, saved[1]
        except Exception:
            pass
    geoms = build_geometries(paths, cfg.clean)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps((stamp, geoms)))
    return paths, geoms


def red_mask(img: Image.Image) -> np.ndarray:
    """Exact (255,0,0) plus a 1 px 4-connected tolerance ring."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.int32)
    exact = (
        (rgb[..., 0] == 255) & (rgb[..., 1] == 0) & (rgb[..., 2] == 0)
    )
    return ndimage.binary_dilation(exact, structure=_CROSS, iterations=1)


def province_label_image(geoms, names, reg, size):
    """Rasterise every province to its 1-based index in image space."""
    scale, (ox, oy) = reg["scale"], reg["offset"]
    img = Image.new("I", size, 0)
    draw = ImageDraw.Draw(img)
    order = []
    for idx, name in enumerate(names, start=1):
        parts = geoms.get(name)
        if not parts:
            continue
        order.append(name)
        for part in sorted(parts, key=lambda p: -p.area):
            ring = [
                ((x - ox) * scale, (y - oy) * scale)
                for x, y in part.exterior.coords
            ]
            draw.polygon(ring, fill=idx)
            for hole in part.interiors:
                hring = [
                    ((x - ox) * scale, (y - oy) * scale)
                    for x, y in hole.coords
                ]
                draw.polygon(hring, fill=0)
    return np.asarray(img, dtype=np.int32), order


def draw_province_outlines(
    draw: ImageDraw.ImageDraw, geoms, names, reg, color, width=1
) -> None:
    """Stroke province part borders onto the markup image space."""
    scale, (ox, oy) = reg["scale"], reg["offset"]
    for name in names:
        for part in geoms.get(name) or []:
            ring = [
                ((x - ox) * scale, (y - oy) * scale)
                for x, y in part.exterior.coords
            ]
            draw.line(ring, fill=color, width=width, joint="curve")


def render_region(
    geoms_mod, frame, ppu, fills
) -> Image.Image:
    """Render province polygons in a base-coords rect at ``ppu`` px/unit."""
    x0, y0, x1, y1 = frame
    w, h = round((x1 - x0) * ppu), round((y1 - y0) * ppu)
    img = Image.new("RGB", (w, h), (30, 53, 71))  # sea colour background
    draw = ImageDraw.Draw(img)
    for name in sorted(geoms_mod):
        fill = fills.get(name, (140, 140, 140))
        for part in geoms_mod[name]:
            ring = [
                ((x - x0) * ppu, (y - y0) * ppu)
                for x, y in part.exterior.coords
            ]
            draw.polygon(ring, fill=fill)
            for hole in part.interiors:
                hr = [
                    ((x - x0) * ppu, (y - y0) * ppu)
                    for x, y in hole.coords
                ]
                draw.polygon(hr, fill=(62, 107, 132))
    # borders on top
    for name in sorted(geoms_mod):
        for part in geoms_mod[name]:
            ring = [
                ((x - x0) * ppu, (y - y0) * ppu)
                for x, y in part.exterior.coords
            ]
            draw.line(ring, fill=(58, 58, 58), width=1, joint="curve")
    return img


# Proposed Alexandria patch polygon (base coords) — see Phase A report.
PATCH_POLYGON = [
    (662.90, 224.55),
    (662.75, 225.40),
    (662.60, 225.90),
    (662.55, 226.45),
    (665.50, 226.45),
    (665.50, 223.90),
    (663.40, 223.90),
]


def write_images(rows, geoms, reg, img: Image.Image) -> None:
    excluded_names = [
        r["name"] for r in rows
        if r["decided"] or (r["frac"] or 0) >= RED_EXCLUDE
    ]
    uncertain_names = [
        r["name"]
        for r in rows
        if not r["decided"]
        and r["frac"] is not None
        and RED_UNCERTAIN <= (r["frac"] or 0) < RED_EXCLUDE
    ]
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    draw_province_outlines(d, geoms, excluded_names, reg, (255, 255, 0), 2)
    draw_province_outlines(d, geoms, uncertain_names, reg, (0, 255, 255), 2)
    out.save(REF / "analysis_exclusions.png")

    # Faraveh zoomed crop (it is ~outside the frame's east edge).
    for r in rows:
        if r["name"] == "Faraveh":
            pass
    crop = out.crop((1290, 960, 1328, 1080)).resize((38 * 4, 120 * 4))
    crop.save(REF / "analysis_uncertain_faraveh.png")

    # Alexandria before/after at 4x the markup scale (6 px/u -> 24 px/u).
    frame = (658.0, 220.0, 672.0, 230.0)
    scale, (ox, oy) = reg["scale"], reg["offset"]
    px0 = round((frame[0] - ox) * scale)
    py0 = round((frame[1] - oy) * scale)
    px1 = round((frame[2] - ox) * scale)
    py1 = round((frame[3] - oy) * scale)
    before = img.convert("RGB").crop((px0, py0, px1, py1))
    ppu = scale * 4
    before = before.resize(
        (before.width * 4, before.height * 4), Image.NEAREST
    )

    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    poly = Polygon(PATCH_POLYGON)
    buh = unary_union(geoms["Buhayra"])
    alex = unary_union(geoms["Alexandria"])
    cut = buh.intersection(poly)
    after_geoms = {}
    for name in (
        "Alexandria", "Buhayra", "Gharbiyya", "Cairo",
        "Dakahliyya", "Sharqiyya", "Red_Sea_Coast",
    ):
        for part in geoms[name]:
            after_geoms.setdefault(name, []).append(part)
    after_geoms["Buhayra"] = [buh.difference(poly)]
    after_geoms["Alexandria"] = [alex.union(cut)]
    fills = {
        "Buhayra": (42, 42, 42),          # excluded desert -> outside
        "Red_Sea_Coast": (42, 42, 42),    # already excluded
    }
    after = render_region(after_geoms, frame, ppu, fills)
    da = ImageDraw.Draw(after)
    pring = [((x - frame[0]) * ppu, (y - frame[1]) * ppu)
             for x, y in poly.exterior.coords]
    da.line(pring, fill=(76, 255, 0), width=2, joint="curve")

    combo = Image.new("RGB", (before.width + after.width + 8,
                              max(before.height, after.height)),
                      (20, 20, 20))
    combo.paste(before, (0, 0))
    combo.paste(after, (before.width + 8, 0))
    combo.save(REF / "analysis_alexandria_before_after.png")


def main() -> int:
    cfg = load_pipeline_config()
    reg = json.loads((REF / "boundary_v2_markup.registration.json").read_text())
    img = Image.open(REF / "boundary_v2_markup.png")
    W, H = img.size
    boundary = load_boundary(DATA / "boundary.yaml")
    overrides = load_overrides(DATA / "overrides.yaml")
    lock = load_ids_lock(DATA / "ids.lock.json")
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    paths, geoms = load_geoms(DATA, cfg)

    red = red_mask(img)
    labels, order = province_label_image(
        geoms, boundary.include, reg, (W, H)
    )
    n = len(boundary.include)
    total = np.bincount(labels.ravel(), minlength=n + 1)
    redcnt = np.bincount(labels.ravel()[red.ravel()], minlength=n + 1)

    rows = []
    for i, name in enumerate(boundary.include, start=1):
        area_px = int(total[i])
        red_px = int(redcnt[i])
        frac = (red_px / area_px) if area_px else None
        rows.append(
            {
                "name": name,
                "key": name.lower(),
                "id": lock.ids.get(name.lower()),
                "area_px": area_px,
                "red_px": red_px,
                "frac": frac,
                "decided": name in DECIDED_EXCLUDE,
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "red_fractions.json").write_text(
        json.dumps(rows, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    excl = [r for r in rows if r["decided"] or (r["frac"] or 0) >= RED_EXCLUDE]
    unc = [
        r
        for r in rows
        if not r["decided"]
        and r["frac"] is not None
        and RED_UNCERTAIN <= r["frac"] < RED_EXCLUDE
    ]
    keep = [
        r
        for r in rows
        if not r["decided"] and (r["frac"] or 0) < RED_UNCERTAIN
    ]
    print(f"include provinces: {len(rows)}")
    print(f"exclude (>= {RED_EXCLUDE} or decided): {len(excl)}")
    print(f"uncertain ({RED_UNCERTAIN}..{RED_EXCLUDE}): {len(unc)}")
    print(f"keep (< {RED_UNCERTAIN}): {len(keep)}")
    print(f"outside image (frac=None): "
          f"{[r['name'] for r in rows if r['frac'] is None]}")
    print("\n== EXCLUDE ==")
    for r in sorted(excl, key=lambda r: -(r["frac"] or 0)):
        note = " [decided]" if r["decided"] else ""
        print(f"  {r['name']:32s} id={r['id']} frac={r['frac']}{note}")
    print("\n== UNCERTAIN ==")
    for r in sorted(unc, key=lambda r: -(r["frac"] or 0)):
        print(f"  {r['name']:32s} id={r['id']} frac={r['frac']:.3f}")

    write_images(rows, geoms, reg, img)
    return 0


if __name__ == "__main__":
    sys.exit(main())
