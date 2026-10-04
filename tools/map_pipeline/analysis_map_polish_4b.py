"""map_polish_4 Phase B verification: before/after metrics and crops.

Compares the committed (HEAD, "before") geometry with the freshly built
("after") ``data/map/geometry.json``. Read-only for data/**; writes crops
to ``tools/map_pipeline/reference/`` and a numbers dump to
``tools/map_pipeline/out/analysis/``.

Run:  python -m tools.map_pipeline.analysis_map_polish_4b
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Point, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "map"
REF = ROOT / "tools" / "map_pipeline" / "reference"
OUT = ROOT / "tools" / "map_pipeline" / "out" / "analysis"

sys.path.insert(0, str(ROOT))
from tools.map_pipeline.svgpath import parse_path  # noqa: E402
from tools.map_pipeline.pipeline_config_schema import (  # noqa: E402
    load_pipeline_config,
)
from tools.map_pipeline.preview import render_map_preview  # noqa: E402

CFG = load_pipeline_config()
VIEW = box(0.0, 0.0, float(CFG.view.width), float(CFG.view.height))
TOUCH_EPS = 0.02

WATCH = ["cafa", "ionian_islands", "halland", "lule_lappmark"]

CROPS = {
    "cyclades": (632.0, 182.0, 662.0, 209.0),
    "danish_straits": (588.0, 102.0, 616.0, 124.0),
    "ionian": (623.0, 183.0, 636.0, 199.0),
    "cafa": (673.0, 155.0, 689.0, 168.0),
    "halland": (599.0, 97.0, 611.0, 110.0),
    "lappmark": (614.0, 38.0, 640.0, 58.0),
}


def _parts(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in geom.geoms if g.geom_type == "Polygon"]


def _load(geom_path: Path, mani_path: Path):
    geom = json.loads(geom_path.read_text(encoding="utf-8"))
    mani = json.loads(mani_path.read_text(encoding="utf-8"))
    by_key = {
        n["key"]: parse_path(geom["paths"][str(n["id"])])
        for n in mani["nodes"]
    }
    meta = {n["key"]: n for n in mani["nodes"]}
    outside = parse_path(geom["outside"])
    sea_water = parse_path(geom["sea_water"]) if geom["sea_water"] else []
    sea_ids = {
        str(n["id"]) for n in mani["nodes"] if n["kind"] == "SEA"
    }
    return geom, mani, by_key, meta, outside, sea_water, sea_ids


def head_docs():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name in ("geometry.json", "manifest.json"):
            blob = subprocess.run(
                ["git", "show", f"HEAD:data/map/{name}"],
                cwd=ROOT, capture_output=True, check=True,
            ).stdout
            (td / name).write_bytes(blob)
        return _load(td / "geometry.json", td / "manifest.json")


def water_slivers(by_key, outside, sea_water):
    """Water-visible pieces >= 0.002 u2 inside `outside`, by touch."""
    nodes_u = unary_union([p for ps in by_key.values() for p in ps])
    windows = VIEW.difference(unary_union(outside))
    water = windows
    if sea_water:
        water = unary_union([windows, unary_union(sea_water)])
    pieces = [
        p for p in _parts(water.difference(nodes_u)) if p.area >= 0.002
    ]
    touching = [p for p in pieces if p.distance(nodes_u) <= TOUCH_EPS]
    far = [p for p in pieces if p.distance(nodes_u) > TOUCH_EPS]
    return {
        "pieces": len(pieces),
        "touching": len(touching),
        "no_node": len(far),
        "no_node_area": round(sum(p.area for p in far), 3),
    }


def small_part_stats(by_key, meta):
    total = low_vert = 0
    for key, parts in by_key.items():
        if meta[key]["kind"] != "LAND":
            continue
        for p in parts:
            if p.area < 3.0:
                total += 1
                if len(p.exterior.coords) - 1 <= 6:
                    low_vert += 1
    return {"parts_below_3": total, "at_most_6_vertices": low_vert}


def overlaps(by_key, meta):
    seas = {k for k, n in meta.items() if n["kind"] == "SEA"}
    out = {}
    for key in WATCH:
        land = unary_union(by_key[key])
        per_zone = {}
        for s in sorted(seas):
            inter = land.intersection(unary_union(by_key[s]))
            if inter.area > 1e-9:
                per_zone[s] = round(inter.area, 4)
        out[key] = per_zone
    return out


def ionian_cover(by_key):
    parts = by_key["ionian_islands"]
    sea = unary_union(by_key["sea_ionian"])
    return [
        round(p.intersection(sea).area / p.area, 3) for p in parts
    ]


def sea_structure(by_key, meta):
    seas = sorted(k for k, n in meta.items() if n["kind"] == "SEA")
    res = {}
    for s in seas:
        g = unary_union(by_key[s])
        res[s] = {
            "parts": len(_parts(g)),
            "area": round(g.area, 2),
            "anchor_inside": g.covers(Point(*meta[s]["anchor"])),
        }
    return res


def seam_band(by_key, meta, outside):
    """Outside pieces sandwiched within 0.05 of both land and sea."""
    land = unary_union(
        [
            p
            for k, ps in by_key.items()
            if meta[k]["kind"] != "SEA"
            for p in ps
        ]
    )
    sea = unary_union(
        [
            p
            for k, ps in by_key.items()
            if meta[k]["kind"] == "SEA"
            for p in ps
        ]
    )
    out_u = unary_union(outside)
    band = out_u.intersection(land.buffer(0.05)).intersection(
        sea.buffer(0.05)
    )
    pieces = [p for p in _parts(band) if p.area > 1e-4]
    return {"pieces": len(pieces), "area": round(band.area, 4)}


def crop_pair(before, after, name, rect, ppu):
    bg, *_ = before
    ag, *_ = after
    colors = CFG.preview.colors

    def render(docs):
        _g, _m, by_key, meta, outside, sea_water, sea_ids = docs
        paths = {
            str(meta[k]["id"]): ps
            for k, ps in by_key.items()
            if box(*rect).intersects(unary_union(ps))
        }
        ids = {str(meta[k]["id"]) for k in by_key
               if meta[k]["kind"] == "SEA"}
        return render_map_preview(
            paths, outside, rect, ppu, colors,
            sea_ids=ids, sea_water_parts=sea_water,
        )

    ib, ia = render(before), render(after)
    gap = 8
    img = Image.new("RGB", (ib.width + ia.width + gap, ib.height),
                    (255, 255, 255))
    img.paste(ib, (0, 0))
    img.paste(ia, (ib.width + gap, 0))
    d = ImageDraw.Draw(img)
    d.text((4, 4), "BEFORE", fill=(255, 80, 80))
    d.text((ib.width + gap + 4, 4), "AFTER", fill=(0, 120, 0))
    out = REF / f"analysis_map_polish_4b_{name}.png"
    img.save(out)
    return out.name


def main() -> int:
    before = head_docs()
    after = _load(DATA / "geometry.json", DATA / "manifest.json")
    OUT.mkdir(parents=True, exist_ok=True)

    rep = {"geometry_version": after[0]["version"]}
    rep["rash_before"] = water_slivers(before[2], before[4], before[5])
    rep["rash_after"] = water_slivers(after[2], after[4], after[5])
    rep["small_parts_before"] = small_part_stats(before[2], before[3])
    rep["small_parts_after"] = small_part_stats(after[2], after[3])
    rep["overlaps_before"] = overlaps(before[2], before[3])
    rep["overlaps_after"] = overlaps(after[2], after[3])
    rep["ionian_cover_before"] = ionian_cover(before[2])
    rep["ionian_cover_after"] = ionian_cover(after[2])
    rep["sea_before"] = sea_structure(before[2], before[3])
    rep["sea_after"] = sea_structure(after[2], after[3])
    rep["seam_band_before"] = seam_band(before[2], before[3], before[4])
    rep["seam_band_after"] = seam_band(after[2], after[3], after[4])

    deltas = sorted(
        (
            (k, round(a["area"] - rep["sea_before"][k]["area"], 2))
            for k, a in rep["sea_after"].items()
        ),
        key=lambda t: abs(t[1]),
        reverse=True,
    )
    rep["sea_area_deltas_top5"] = deltas[:5]
    bad = [
        s for s, a in rep["sea_after"].items()
        if not a["anchor_inside"]
        or a["parts"] != rep["sea_before"][s]["parts"]
    ]
    rep["sea_structure_issues"] = bad

    (OUT / "map_polish_4b.json").write_text(
        json.dumps(rep, indent=1, sort_keys=True), encoding="utf-8"
    )
    for k, v in rep.items():
        if k not in ("sea_before", "sea_after"):
            print(k, "=", v)

    # Crops: max-zoom (40 px/u) pairs for all regions + z=1 (5 px/u) for
    # the three gap-watch coasts.
    for name, rect in CROPS.items():
        print(crop_pair(before, after, name, rect, 40))
    for name in ("ionian", "cafa", "halland"):
        print(crop_pair(before, after, f"{name}_z1", CROPS[name], 5))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
