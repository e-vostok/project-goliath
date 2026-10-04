"""map_polish_4 Phase A — coastline cosmetics diagnosis (read-only).

Reads ``data/map/geometry.json`` + ``manifest.json`` + the saved sea raster
and the source geometries (cached); writes NOTHING to ``data/``.

Images  -> ``tools/map_pipeline/reference/analysis_map_polish_4_*.png``
Numbers -> ``tools/map_pipeline/out/analysis/map_polish_4.json``

Sections:
 1. remaining water slivers on dark/excluded coasts (windows of ``outside``
    that no node touches);
 2. straight edges of playable LAND nodes not shared with another boundary;
 3. small-island simplification at the current ``simplify.tolerance`` and
    the byte/vertex cost of candidate fixes;
 4. hover/selection outline vs the drawn borders (overlap measurement).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw
from shapely import STRtree, maximum_inscribed_circle
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from .analysis_boundary_v2 import DATA, OUT, REF, load_geoms
from .geometry import _clean_hairpins, _snap_pointwise, deviation
from .models import load_boundary, load_overrides
from .pipeline_config_schema import PreviewColors, load_pipeline_config
from .preview import _rgb, render_map_preview
from .seas import (
    KIND_BAY,
    KIND_LAKE,
    KIND_LAND,
    KIND_UNKNOWN_SEA,
    KIND_ZONE_WATER,
)
from .svg_source import safe_union
from .svgpath import dumps, parse_path

RASTER = Path("tools/map_pipeline/out")
STRAIGHT_DELTA = 0.015          # chord flatness band, units
STRAIGHT_MIN_LEN = 0.5          # report straight chords at least this long
SHARE_EPS = 0.08                # "same seam" distance (~2 * (tol + grid))
SMALL_PART_AREA = 3.0
SMALL_PART_VERTS = 6
PX_PER_UNIT_Z1 = 4.97           # z=1, 1080 px window / frame height 217.3

KIND_NAME = {
    KIND_LAND: "land",
    KIND_ZONE_WATER: "zone",
    KIND_UNKNOWN_SEA: "unknown",
    KIND_LAKE: "lake",
    KIND_BAY: "bay",
    -1: "off-raster",
}

REGIONS = {
    "lappmark_norway": (555.0, 4.0, 700.0, 60.0),
    "kola_white_sea": (650.0, 20.0, 782.0, 80.0),
    "algeria_tunisia": (578.0, 194.0, 676.0, 266.0),
}
ISLAND_REGIONS = {
    "cyclades": (632.0, 182.0, 662.0, 209.0),
    "danish_straits": (588.0, 102.0, 616.0, 124.0),
    "ionian": (623.0, 183.0, 636.0, 199.0),
}


def _parts(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return list(geom.geoms)


def _poly_list(geom) -> list[Polygon]:
    out = []
    for p in _parts(geom):
        if p.area > 0:
            out.append(p)
    return out


def kind_at(kinds, frame, x, y) -> int:
    x0, y0, _x1, _y1, r = frame
    col = int(round((x - x0) * r))
    row = int(round((y - y0) * r))
    if 0 <= col < kinds.shape[1] and 0 <= row < kinds.shape[0]:
        return int(kinds[row, col])
    return -1


# ------------------------------------------------------------ section 1


def water_components(view_poly, outside_parts, node_parts):
    """Visible water = view_box - outside - node fills, as polygons."""
    cover = unary_union([*outside_parts, *node_parts])
    water = view_poly.difference(cover)
    return _poly_list(water)


def sliver_table(comps, nodes_u, kinds, frame):
    rows = []
    for comp in comps:
        rp = comp.representative_point()
        k = kind_at(kinds, frame, rp.x, rp.y)
        mic = maximum_inscribed_circle(comp)
        centre = Point(mic.coords[0])
        radius = float(comp.boundary.distance(centre)) if comp.area else 0.0
        region = "other"
        for name, (x0, y0, x1, y1) in REGIONS.items():
            if x0 <= rp.x <= x1 and y0 <= rp.y <= y1:
                region = name
        rows.append(
            {
                "area": round(comp.area, 4),
                "thickness": round(2 * radius, 3),
                "kind": KIND_NAME.get(k, str(k)),
                "touches_node": comp.distance(nodes_u) < 0.02,
                "region": region,
                "rp": (round(rp.x, 2), round(rp.y, 2)),
                "geom": comp,
            }
        )
    rows.sort(key=lambda r: -r["area"])
    return rows


# ------------------------------------------------------------ section 2


def straight_runs(coords, delta=STRAIGHT_DELTA, min_len=STRAIGHT_MIN_LEN,
                  cap=4000):
    """Maximal vertex runs whose intermediate points stay within ``delta``
    of the chord, with chord length >= ``min_len``. Ring indices only."""
    pts = np.asarray(coords[:-1], dtype=float)
    n = len(pts)
    runs = []
    i = 0
    while i < n - 2:
        a = pts[i]
        best = None
        j = i + 2
        jmax = min(n, i + cap)
        while j < jmax:
            b = pts[j]
            v = b - a
            L = float(np.hypot(v[0], v[1]))
            if L < 1e-9:
                j += 1
                continue
            w = pts[i + 1 : j] - a
            dev = np.abs(w[:, 0] * v[1] - w[:, 1] * v[0]) / L
            if dev.size and dev.max() > delta:
                break
            if L >= min_len:
                best = (i, j, L)
            j += 1
        if best is not None:
            runs.append(best)
            i = best[1]
        else:
            i += 1
    # single edges >= min_len are perfectly straight cuts too (a hard
    # clip emits ONE long edge, not a vertex run).
    covered = np.zeros(n, dtype=bool)
    for i, j, _L in runs:
        covered[i:j] = True
    for i in range(n - 1):
        if covered[i]:
            continue
        L = float(np.hypot(*(pts[i + 1] - pts[i])))
        if L >= min_len:
            runs.append((i, i + 1, L))
            covered[i + 1] = True
    return runs


def collect_boundary_segments(node_parts_by_id, outside_parts, extra):
    """Every boundary ring segment tagged by owner."""
    segs = []
    owners = []

    def add_ring(ring_coords, owner):
        pts = list(ring_coords)
        for k in range(len(pts) - 1):
            if pts[k] != pts[k + 1]:
                segs.append(LineString([pts[k], pts[k + 1]]))
                owners.append(owner)

    for nid, parts in node_parts_by_id.items():
        for p in parts:
            add_ring(p.exterior.coords, ("node", nid))
            for hole in p.interiors:
                add_ring(hole.coords, ("node", nid))
    for p in outside_parts:
        add_ring(p.exterior.coords, ("outside", 0))
        for hole in p.interiors:
            add_ring(hole.coords, ("outside", 0))
    for owner, poly in extra.items():
        for part in _poly_list(poly):
            add_ring(part.exterior.coords, (owner, 0))
            for hole in part.interiors:
                add_ring(hole.coords, (owner, 0))
    return segs, owners, STRtree(segs)


def covered_fraction(chord: LineString, segs, owners, tree, skip_owner,
                     eps=SHARE_EPS):
    """Fraction of ``chord`` within ``eps`` of other owners' segments."""
    L = chord.length
    if L == 0:
        return 1.0, {}
    band = chord.buffer(eps)
    idx = tree.query(band)
    d = np.array(
        [chord.coords[1][0] - chord.coords[0][0],
         chord.coords[1][1] - chord.coords[0][1]]
    ) / L
    o = np.array(chord.coords[0])
    by_src: dict[str, list] = {}
    for i in idx:
        owner = owners[i]
        if owner == skip_owner:
            continue
        piece = segs[i].intersection(band)
        if piece.is_empty:
            continue
        geoms = [piece] if piece.geom_type in (
            "LineString", "Point") else list(piece.geoms)
        for g in geoms:
            if g.geom_type == "Point":
                tvals = [float(np.dot(np.array(g.coords[0]) - o, d))]
            elif g.geom_type in ("LineString", "MultiPoint"):
                tvals = [
                    float(np.dot(np.array(c) - o, d)) for c in g.coords
                ]
            else:
                continue
            lo, hi = max(0.0, min(tvals)), min(L, max(tvals))
            if hi > lo:
                by_src.setdefault(owner[0], []).append((lo, hi))
    per_src = {}
    for src, ivs in by_src.items():
        ivs.sort()
        merged = []
        for lo, hi in ivs:
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        per_src[src] = sum(hi - lo for lo, hi in merged) / L
    return sum(per_src.values()), per_src


# ------------------------------------------------------------ section 3


def refinalize(parts, tol_of_area, grid):
    """_finalize_land with a per-part tolerance rule (estimate only)."""
    out = []
    for part in sorted(parts, key=lambda p: (-p.area, p.bounds)):
        t = tol_of_area(part.area)
        out.extend(
            _snap_pointwise(part.simplify(t, preserve_topology=True), grid)
        )
    return out


def island_stats(node_parts_by_id):
    """Small parts in the current geometry: counts and vertex stats."""
    small = []
    for nid, parts in node_parts_by_id.items():
        for p in parts:
            if p.area < SMALL_PART_AREA:
                small.append(
                    {
                        "id": nid,
                        "area": round(p.area, 3),
                        "verts": len(p.exterior.coords) - 1,
                        "rp": tuple(
                            round(v, 2)
                            for v in p.representative_point().coords[0]
                        ),
                    }
                )
    return small


# ------------------------------------------------------------ rendering


def client_colors():
    """Post-map_polish_3b palette (configs/01_map.yaml: one water colour)."""
    return PreviewColors.model_validate(
        {
            "inland_water": "#1E3547",
            "outside": "#2A2A2A",
            "sea": "#1E3547",
            "land": "#8C8C8C",
            "border": "#3A3A3A",
            "sea_border": "#2C4A62",
        }
    )


def draw_polys(draw, parts, origin, ppu, fill=None, outline=None,
               width=1, hole_fill=(30, 53, 71)):
    ox, oy = origin

    def xy(ring):
        return [
            ((x - ox) * ppu, (y - oy) * ppu) for x, y in ring.coords
        ]

    for p in parts:
        if fill is not None:
            draw.polygon(xy(p.exterior), fill=fill)
            for hole in p.interiors:
                draw.polygon(xy(hole), fill=hole_fill)
        if outline is not None:
            draw.line(xy(p.exterior), fill=outline, width=width,
                      joint="curve")
            for hole in p.interiors:
                draw.line(xy(hole), fill=outline, width=width,
                          joint="curve")


def main() -> int:
    cfg = load_pipeline_config()
    geom = json.loads((DATA / "geometry.json").read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    boundary = load_boundary(DATA / "boundary.yaml")
    overrides = load_overrides(DATA / "overrides.yaml")
    map_cfg = yaml.safe_load(
        Path("configs/01_map.yaml").read_text(encoding="utf-8")
    )
    kinds = np.load(RASTER / "sea_kinds.npy")
    sr = json.loads((RASTER / "sea_raster.json").read_text(encoding="utf-8"))
    frame = (*sr["frame"][:2], *sr["frame"][2:], sr["pixels_per_unit"])

    nodes_meta = {n["id"]: n for n in manifest["nodes"]}
    sea_ids = {n["id"] for n in manifest["nodes"] if n["kind"] == "SEA"}
    land_ids = set(nodes_meta) - sea_ids

    node_parts_by_id = {
        int(k): parse_path(d) for k, d in geom["paths"].items()
    }
    outside_parts = parse_path(geom["outside"])
    sea_water_parts = (
        parse_path(geom["sea_water"]) if geom["sea_water"] else []
    )
    all_node_parts = [p for ps in node_parts_by_id.values() for p in ps]
    print("geometry parsed:",
          len(node_parts_by_id), "nodes,",
          sum(len(p.exterior.coords) for ps in node_parts_by_id.values()
              for p in ps), "exterior pts")

    print("union nodes ...", flush=True)
    nodes_u = unary_union(all_node_parts)
    view_poly = box(0, 0, 1200, 680)

    # ------------------------------------------------------- 1 slivers
    comps = water_components(view_poly, outside_parts, all_node_parts)
    rows = sliver_table(comps, nodes_u, kinds, frame)
    dark = [r for r in rows if not r["touches_node"] and r["area"] >= 0.002]
    print(f"\nwater-visible components: {len(rows)} "
          f"(>=0.002, not touching any node: {len(dark)})")
    by_kind: dict[str, list] = {}
    for r in dark:
        by_kind.setdefault(r["kind"], []).append(r)
    for k, rr in sorted(by_kind.items()):
        print(f"  {k}: {len(rr)} pieces, "
              f"area {sum(x['area'] for x in rr):.3f}")
    for region in REGIONS:
        rr = [r for r in dark if r["region"] == region]
        print(f"  region {region}: {len(rr)} slivers, "
              f"area {sum(x['area'] for x in rr):.3f}, "
              f"thickest {max((x['thickness'] for x in rr), default=0):.3f}")
    print("  largest dark slivers:")
    for r in dark[:15]:
        print(f"    area={r['area']:<7} thick={r['thickness']:<6} "
              f"{r['kind']:<8} {r['region']:<18} rp={r['rp']}")

    # ------------------------------------------------- 2 straight edges
    print("\ncollecting boundary segments ...", flush=True)
    fr = map_cfg["view"]["frame"]
    extra = {
        "frame": box(fr["x"], fr["y"], fr["x"] + fr["width"],
                     fr["y"] + fr["height"]),
        "viewbox": box(0, 0, 1200, 680),
        "patch": Polygon(
            [p.as_tuple()
             for p in overrides.geometry_patches[0].transfer.polygon]
        ) if overrides.geometry_patches else MultiPolygon(),
    }
    segs, owners, tree = collect_boundary_segments(
        node_parts_by_id, outside_parts, extra
    )
    print(f"  {len(segs)} segments")

    source_name = {n["id"]: n["key"] for n in manifest["nodes"]}
    _paths, src_geoms = load_geoms(DATA, cfg)
    # source boundary segments per node key for the 'in source' test
    src_segs: dict[int, list] = {}
    src_trees: dict[int, STRtree] = {}
    name_by_id = {
        n["id"]: n["source_name"] for n in manifest["nodes"]
    }
    for nid in land_ids:
        plist = src_geoms.get(name_by_id[nid]) or []
        ss = []
        for p in plist:
            c = list(p.exterior.coords)
            for k in range(len(c) - 1):
                ss.append(LineString([c[k], c[k + 1]]))
        src_segs[nid] = ss
        src_trees[nid] = STRtree(ss) if ss else None

    straight_report = []
    for nid in sorted(land_ids):
        for pi, part in enumerate(node_parts_by_id[nid]):
            coords = part.exterior.coords
            for (i, j, L) in straight_runs(coords):
                chord = LineString(
                    [tuple(coords[i]), tuple(coords[j])]
                )
                cov, per_src = covered_fraction(
                    chord, segs, owners, tree, ("node", nid)
                )
                src_cov = 0.0
                st = src_trees.get(nid)
                if st is not None:
                    # 0.045 > tol+grid: an "in source" chord means the
                    # SOURCE edge was already straight; a pipeline-made
                    # cut can sit up to ~tol+grid off the true border.
                    band = chord.buffer(0.045)
                    sidx = st.query(band)
                    hit_len = 0.0
                    for si in sidx:
                        piece = src_segs[nid][si].intersection(band)
                        hit_len += piece.length
                    src_cov = min(1.0, hit_len / max(chord.length, 1e-9))
                mid = chord.interpolate(0.5, normalized=True)
                straight_report.append(
                    {
                        "id": nid,
                        "key": source_name[nid],
                        "len": round(L, 2),
                        "shared": round(cov, 2),
                        "by": {k: round(v, 2) for k, v in per_src.items()},
                        "in_source": round(src_cov, 2),
                        "mid": (round(mid.x, 2), round(mid.y, 2)),
                        "chord": chord,
                    }
                )
    unshared = [
        r for r in straight_report
        if r["shared"] < 0.7 and r["in_source"] < 0.7
    ]
    coastal_straight = [
        r for r in straight_report
        if r["in_source"] < 0.7
        and r["by"].get("node", 0.0) < 0.3
        and r["by"].get("outside", 0.0) >= 0.5
    ]
    print(f"\nstraight runs >= {STRAIGHT_MIN_LEN} on LAND exteriors: "
          f"{len(straight_report)}; unshared & not-in-source: "
          f"{len(unshared)}; coastal straight not-in-source: "
          f"{len(coastal_straight)}")
    for r in sorted(unshared, key=lambda r: -r["len"])[:30]:
        print(f"    {r['key']:<22} len={r['len']:<5} shared={r['shared']} "
              f"by={r['by']} src={r['in_source']} mid={r['mid']}")
    for r in sorted(coastal_straight, key=lambda r: -r["len"])[:30]:
        print(f"    [coast] {r['key']:<22} len={r['len']:<5} "
              f"by={r['by']} src={r['in_source']} mid={r['mid']}")

    # straight runs on SEA zone exteriors (sea-margin / playable cuts)
    sea_straight = []
    for nid in sorted(sea_ids):
        for part in node_parts_by_id[nid]:
            coords = part.exterior.coords
            for (i, j, L) in straight_runs(coords):
                chord = LineString(
                    [tuple(coords[i]), tuple(coords[j])]
                )
                cov, per_src = covered_fraction(
                    chord, segs, owners, tree, ("node", nid)
                )
                mid = chord.interpolate(0.5, normalized=True)
                sea_straight.append(
                    {
                        "id": nid,
                        "key": source_name[nid],
                        "len": round(L, 2),
                        "shared": round(cov, 2),
                        "by": {k: round(v, 2) for k, v in per_src.items()},
                        "mid": (round(mid.x, 2), round(mid.y, 2)),
                    }
                )
    sea_cut = [
        r for r in sea_straight
        if r["by"].get("node", 0.0) < 0.3
    ]
    print(f"SEA straight runs: {len(sea_straight)}; "
          f"edge not shared with another zone/land: {len(sea_cut)}")
    for r in sorted(sea_cut, key=lambda r: -r["len"])[:20]:
        print(f"    [sea] {r['key']:<22} len={r['len']:<5} "
              f"by={r['by']} mid={r['mid']}")

    # classify every straight run inside the named screenshot places
    places = {
        "alexandria_strip": (658.0, 220.0, 672.0, 232.0),
        "egypt_coast": (620.0, 222.0, 675.0, 252.0),
        "lappmark_coast": (600.0, 8.0, 700.0, 55.0),
        "kola_coast": (650.0, 25.0, 780.0, 80.0),
    }

    def classify(r):
        by = r["by"]
        if by.get("patch", 0) >= 0.5:
            return "intended (geometry_patches edge)"
        if by.get("viewbox", 0) >= 0.5 or by.get("frame", 0) >= 0.5:
            return "intended (view_box/view.frame edge)"
        if by.get("node", 0) >= 0.7:
            return "shared seam (neighbour/sea border)"
        if r.get("in_source", 0) >= 0.7:
            return "intended (straight already in source SVG)"
        if "in_source" not in r:
            return "sea-cut artefact (raster/margin cut edge)"
        return "simplification or other artefact"

    print("\nnamed-place straight runs (land + sea):")
    for pname, (x0, y0, x1, y1) in places.items():
        hits = [
            r for r in [*straight_report, *sea_straight]
            if x0 <= r["mid"][0] <= x1 and y0 <= r["mid"][1] <= y1
        ]
        print(f"  {pname}: {len(hits)}")
        for r in sorted(hits, key=lambda r: -r["len"])[:8]:
            print(
                f"    {r['key']:<22} len={r['len']:<5} mid={r['mid']} "
                f"-> {classify(r)}"
            )

    # ------------------------------------------------------- 3 islands
    small = island_stats(
        {nid: ps for nid, ps in node_parts_by_id.items() if nid in land_ids}
    )
    le6 = [s for s in small if s["verts"] <= SMALL_PART_VERTS]
    print(f"\nLAND parts < {SMALL_PART_AREA}: {len(small)}; "
          f"with <= {SMALL_PART_VERTS} vertices: {len(le6)}")
    key_by_id = source_name
    for s in sorted(le6, key=lambda s: s["area"])[:25]:
        print(f"    id={s['id']} {key_by_id[s['id']]:<24} "
              f"area={s['area']} verts={s['verts']} rp={s['rp']}")

    # candidate tolerance rules -> bytes + small-part vertex survival
    grid = cfg.output.grid
    tol0 = cfg.simplify.tolerance
    options = {
        "t=0.03 (current)": lambda a: tol0,
        "t=0.02 all": lambda a: 0.02,
        "t=0.015 all": lambda a: 0.015,
        "t=0.01 for parts<3": lambda a: 0.01 if a < 3.0 else tol0,
        "t=0.015 for parts<3": lambda a: 0.015 if a < 3.0 else tol0,
        "scaled 0.012*sqrt(a)": lambda a: min(tol0, 0.012 * float(np.sqrt(a))),
    }
    # per-node source parts (drop_parts already irrelevant for islands)
    node_src_parts = {
        nid: [p for p in (src_geoms.get(name_by_id[nid]) or [])]
        for nid in land_ids
    }
    # apply drop_parts like the pipeline (single entry today)
    for d in overrides.drop_parts:
        nid = next(
            (i for i in land_ids if key_by_id[i] == d.key), None
        )
        if nid is not None:
            node_src_parts[nid] = [
                p for p in node_src_parts[nid]
                if not p.buffer(0.01).contains(
                    Point(d.point.x, d.point.y)
                )
            ]
    opt_rows = {name: {"bytes": 0, "le6": 0, "small": 0, "max_dev": 0.0}
                for name in options}
    print("\nsimulating tolerance options ...", flush=True)
    for nid in sorted(land_ids):
        parts = node_src_parts[nid]
        if not parts:
            continue
        cleaned = _clean_hairpins(safe_union(parts), grid)
        plist = _poly_list(cleaned)
        for name, rule in options.items():
            fin = refinalize(plist, rule, grid)
            if not fin:
                continue
            fgeom = fin[0] if len(fin) == 1 else MultiPolygon(fin)
            opt_rows[name]["bytes"] += len(dumps(fgeom))
            for p in fin:
                if p.area < SMALL_PART_AREA:
                    opt_rows[name]["small"] += 1
                    if len(p.exterior.coords) - 1 <= SMALL_PART_VERTS:
                        opt_rows[name]["le6"] += 1
            if name != "t=0.03 (current)":
                dv = deviation(cleaned, fgeom)
                opt_rows[name]["max_dev"] = max(
                    opt_rows[name]["max_dev"], dv
                )
    actual_land_bytes = sum(
        len(geom["paths"][str(i)]) for i in land_ids
    )
    print(f"  actual land path bytes: {actual_land_bytes}")
    for name, r in opt_rows.items():
        print(
            f"  {name:<26} bytes={r['bytes']} "
            f"(delta {r['bytes'] - actual_land_bytes:+d}) "
            f"small={r['small']} <=6v={r['le6']} "
            f"max_dev={r['max_dev']:.3f}"
        )

    # ------------------------------------------------- 4 outline offset
    neighbours: dict[int, list[int]] = {i: [] for i in nodes_meta}
    for e in manifest["edges"]:
        neighbours[e["a"]].append(e["b"])
        neighbours[e["b"]].append(e["a"])
    print("\noutline offset (own d vs later-drawn neighbours):")
    outline_rows = {}
    for nid in (1511, 1170, 1346, 1385):
        A = unary_union(node_parts_by_id[nid])
        later = [b for b in neighbours[nid] if b > nid]
        earlier = [b for b in neighbours[nid] if b < nid]
        rows = []
        for b in later + earlier:
            B = unary_union(node_parts_by_id[b])
            ip = _poly_list(A.intersection(B))
            if not ip:
                continue
            inter = unary_union(ip)
            if inter.is_empty or inter.area < 1e-4:
                continue
            mic = maximum_inscribed_circle(inter)
            depth = float(
                inter.boundary.distance(Point(mic.coords[0]))
            )
            in_len = A.boundary.intersection(B).length
            rows.append(
                {
                    "nb": key_by_id[b],
                    "later": b > nid,
                    "overlap_area": round(inter.area, 4),
                    "depth": round(depth, 3),
                    "depth_px": round(depth * PX_PER_UNIT_Z1, 1),
                    "outline_in_nb": round(in_len, 2),
                }
            )
        # parts of A mostly hidden by later nodes
        hidden = []
        later_u = unary_union(
            [p for b in later for p in node_parts_by_id[b]]
        ) if later else MultiPolygon()
        for p in node_parts_by_id[nid]:
            if not later_u.is_empty:
                cov = p.intersection(later_u).area / p.area
                if cov > 0.5:
                    hidden.append((round(p.area, 2), round(cov, 2)))
        outline_rows[nid] = {"rows": rows, "hidden_parts": hidden}
        print(f"  {key_by_id[nid]} (id {nid}):")
        for r in rows:
            print(
                f"    vs {r['nb']:<20} {'later' if r['later'] else 'earlier'}"
                f" overlap={r['overlap_area']} depth={r['depth']}u "
                f"({r['depth_px']}px@z1) own-border-inside={r['outline_in_nb']}"
            )
        if hidden:
            print(f"    parts >50% covered by later nodes: {hidden}")

    # ------------------------------------------------------- images
    print("\nrendering crops ...", flush=True)
    colors = client_colors()
    ppu = 24
    parsed_str = {str(k): v for k, v in node_parts_by_id.items()}
    sea_str = {str(i) for i in sea_ids}
    for name, rect in REGIONS.items():
        img = render_map_preview(
            parsed_str, outside_parts, rect, ppu, colors,
            sea_str, sea_water_parts,
        )
        d = ImageDraw.Draw(img)
        tagged = [
            r for r in dark
            if r["region"] == name and r["area"] >= 0.003
        ]
        for n_i, r in enumerate(tagged, 1):
            x, y = r["rp"]
            px = ((x - rect[0]) * ppu, (y - rect[1]) * ppu)
            d.ellipse(
                (px[0] - 3, px[1] - 3, px[0] + 3, px[1] + 3),
                outline=(255, 80, 80), width=2,
            )
            d.text((px[0] + 5, px[1] - 6),
                   f"{n_i}:{r['area']}", fill=(255, 200, 60))
        img.save(REF / f"analysis_map_polish_4_rash_{name}.png")
        print(f"  rash_{name}: {len(tagged)} slivers tagged")

    for name, rect in ISLAND_REGIONS.items():
        in_region = [
            nid for nid in land_ids
            if any(
                rect[0] <= p.representative_point().x <= rect[2]
                and rect[1] <= p.representative_point().y <= rect[3]
                for p in node_parts_by_id[nid]
            )
        ]
        ctx_region = [
            nid for nid in land_ids
            if any(
                not box(*p.bounds).intersection(
                    box(rect[0], rect[1], rect[2], rect[3])
                ).is_empty
                for p in node_parts_by_id[nid]
            )
        ]
        # source side: every source province touching the rect (context)
        # plus the region nodes' own parts (the comparison targets)
        src_ctx = [
            p
            for sname, plist in src_geoms.items()
            for p in plist
            if not box(*p.bounds).intersection(
                box(rect[0], rect[1], rect[2], rect[3])
            ).is_empty
        ]
        src_parts = [
            p for nid in in_region
            for p in node_src_parts.get(nid, [])
        ]
        cur_parts = [
            p for nid in ctx_region for p in node_parts_by_id[nid]
        ]
        cur_focus = [
            p for nid in in_region for p in node_parts_by_id[nid]
        ]
        w = round((rect[2] - rect[0]) * ppu)
        h = round((rect[3] - rect[1]) * ppu)
        img = Image.new("RGB", (w * 2 + 8, h), _rgb(colors.sea))
        d = ImageDraw.Draw(img)
        d.text((4, 4), "source SVG", fill=(255, 255, 255))
        d.text((w + 12, 4), "current geometry.json",
               fill=(255, 255, 255))
        draw_polys(d, src_ctx, (rect[0], rect[1]), ppu,
                   fill=(120, 120, 120))
        draw_polys(d, src_parts, (rect[0], rect[1]), ppu,
                   fill=_rgb(colors.land))
        draw_polys(d, src_ctx, (rect[0], rect[1]), ppu,
                   outline=_rgb(colors.border))
        shift = w + 8
        ox, oy = rect[0] - shift / ppu, rect[1]
        draw_polys(d, cur_parts, (ox, oy), ppu, fill=(120, 120, 120))
        draw_polys(d, cur_focus, (ox, oy), ppu, fill=_rgb(colors.land))
        draw_polys(d, cur_parts, (ox, oy), ppu,
                   outline=_rgb(colors.border))
        img.save(REF / f"analysis_map_polish_4_islands_{name}.png")
        print(f"  islands_{name}: {len(in_region)} nodes "
              f"({sorted(key_by_id[i] for i in in_region)[:8]})")

    # numeric dump for the record
    OUT.mkdir(parents=True, exist_ok=True)
    dump = {
        "slivers": [
            {k: v for k, v in r.items() if k != "geom"} for r in dark
        ],
        "unshared_straights": [
            {k: v for k, v in r.items() if k != "chord"}
            for r in unshared
        ],
        "coastal_straights": [
            {k: v for k, v in r.items() if k != "chord"}
            for r in coastal_straight
        ],
        "sea_straights": sea_straight,
        "small_parts": small,
        "options": opt_rows,
        "outline": {
            str(k): v for k, v in outline_rows.items()
        },
    }
    (OUT / "map_polish_4.json").write_text(
        json.dumps(dump, ensure_ascii=False, indent=1, default=str)
        + "\n",
        encoding="utf-8",
    )
    print("\ndump ->", OUT / "map_polish_4.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
