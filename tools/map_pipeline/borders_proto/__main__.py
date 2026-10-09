"""``python -m tools.map_pipeline.borders_proto`` — Phase-A feasibility run.

Reads ``data/map/manifest.json`` + ``geometry.json``, computes canonical
pair borders by the ``owner`` (lower-id contour) and ``mid`` (band
midline) methods, measures junctions / coverage / fill distance / sizes,
then writes into ``tools/map_pipeline/reference/``:

- ``borders_report.json``   all measured numbers
- ``borders_layout_b.json`` the separate-file layout for the chosen method
- ``borders_preview.html``  self-contained preview page
- ``borders_crop_*.png``    40 px/u crops (Germany/France, Balkans, Isles)

Nothing outside ``tools/map_pipeline/reference/borders_*`` is written.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import time
from pathlib import Path

import shapely
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
)

from ..svgpath import canonical_json, format_number
from .compute import (
    EPS,
    JUNC_R,
    MID_TOL,
    PX_PER_UNIT,
    Arc,
    junction_groups,
    label_all,
    load_map,
    midline,
)

CROPS = {
    "germany_france": (556.0, 118.0, 590.0, 150.0),
    "balkans": (614.0, 158.0, 648.0, 192.0),
    "british_isles": (526.0, 96.0, 564.0, 136.0),
}

# ~14 demo states for the preview: seed node keys spread over the field.
SEED_KEYS = [
    "kent", "strathclyde", "pays_france", "burgos", "uppland",
    "krakow", "ober_dem_wienerwald", "pest", "bosnia",
    "constantinople", "corum", "venice", "cairo", "nizhny_novgorod",
]
STATE_CAP = 55


def _line_d(pts, closed=False):
    body = "M " + " ".join(
        f"{format_number(x)} {format_number(y)}" for x, y in pts
    )
    return body + (" Z" if closed else "")


def _dedup_last(pts):
    if len(pts) > 1 and pts[0] == pts[-1]:
        return pts[:-1]
    return pts


def _arc_d(arcs):
    return "".join(
        _line_d(_dedup_last(a.pts) if not a.closed else a.pts, a.closed)
        for a in arcs
    )


def _assign_states(nodes, land_edges, manifest):
    """Multi-source BFS over land+strait edges; free provinces = -1."""
    by_key = {n["key"]: n["id"] for n in manifest["nodes"]}
    adj = {i: [] for i in nodes}
    for e in manifest["edges"]:
        if e["type"] in ("land", "strait") and e["a"] in nodes:
            adj[e["a"]].append(e["b"])
            adj[e["b"]].append(e["a"])
    state = {i: -1 for i in nodes}
    frontier = []
    for s, key in enumerate(SEED_KEYS):
        nid = by_key.get(key)
        if nid is None or nid not in state:
            continue
        state[nid] = s
        frontier.append(nid)
    size = {s: 1 for s in range(len(SEED_KEYS))}
    head = 0
    while head < len(frontier):
        nid = frontier[head]
        head += 1
        s = state[nid]
        for nb in sorted(adj[nid]):
            if state[nb] == -1 and size[s] < STATE_CAP:
                state[nb] = s
                size[s] += 1
                frontier.append(nb)
    return state


def _perimeter(geom):
    return geom.boundary.length


def _sampled_max_dist(pts_list, target_geom, step=0.03):
    """Max over dense samples of every polyline to ``target_geom``."""
    worst = 0.0
    for pts in pts_list:
        line = LineString(pts)
        dense = line.segmentize(step)
        arr = shapely.points(list(dense.coords))
        if len(arr):
            worst = max(worst, float(shapely.distance(arr, target_geom).max()))
    return worst





def run(data_dir: Path, ref_dir: Path, eps: float, method: str) -> dict:
    t0 = time.perf_counter()
    manifest, geometry, nodes, land_edges = load_map(data_dir)
    t_load = time.perf_counter() - t0

    t1 = time.perf_counter()
    arcs_by_pair, coast_arcs = label_all(nodes, eps)
    t_label = time.perf_counter() - t1

    # ------------------------------------------------------- candidates
    t2 = time.perf_counter()
    borders_owner: dict[tuple[int, int], list[Arc]] = {}
    borders_mid: dict[tuple[int, int], list[list]] = {}
    stats = {
        "land_edges": len(land_edges),
        "no_segment": [],
        "short_border": [],
        "b_side_missing": [],
    }
    for a, b, manual in land_edges:
        pair = (a, b)
        sides = arcs_by_pair.get(pair, {"a": [], "b": []})
        ka, kb = nodes[a].key, nodes[b].key
        if not sides["a"] and not sides["b"]:
            stats["no_segment"].append((ka, kb, manual))
            borders_owner[pair] = []
            borders_mid[pair] = []
            continue
        if sides["a"] and not sides["b"]:
            stats["b_side_missing"].append((ka, kb))
        owner_arcs = sides["a"]
        borders_owner[pair] = owner_arcs
        mid_pts = [midline(arc, sides["b"]) for arc in owner_arcs]
        borders_mid[pair] = [
            Arc(a, b, pts, False, arc.j0, arc.j1)
            for arc, pts in zip(owner_arcs, mid_pts)
            if len(pts) >= 2
        ]
        total = sum(a_.length for a_ in owner_arcs)
        if total < 0.05:
            stats["short_border"].append((ka, kb, round(total, 4)))
    t_lines = time.perf_counter() - t2

    # -------------------------------------------------------- junctions
    def _junction_metrics(border_map):
        items = []
        for (a, b), arcs in border_map.items():
            for i, arc in enumerate(arcs):
                if arc.closed or len(arc.pts) < 2:
                    continue
                items.append((f"{a}_{b}#{i}s", arc.pts[0], arc.j0))
                items.append((f"{a}_{b}#{i}e", arc.pts[-1], arc.j1))
        for nid, arcs in coast_arcs.items():
            for i, arc in enumerate(arcs):
                if arc.closed or len(arc.pts) < 2:
                    continue
                items.append((f"c{nid}#{i}s", arc.pts[0], arc.j0))
                items.append((f"c{nid}#{i}e", arc.pts[-1], arc.j1))
        groups = junction_groups(items, JUNC_R)
        spans = sorted(g["span"] for g in groups)
        max_span = spans[-1] if spans else 0.0
        p95 = spans[int(len(spans) * 0.95)] if spans else 0.0
        med = spans[len(spans) // 2] if spans else 0.0
        worst_spur = 0.0
        for g in groups:
            cx, cy = g["centre"]
            for p in g["member_pts"]:
                worst_spur = max(worst_spur, math.hypot(p[0] - cx, p[1] - cy))
        # a healthy junction's key is met by arcs of >=2 rings
        single_ring = sum(
            1
            for g in groups
            if len({m.split("#")[0] for m in g["members"]}) < 2
        )
        worst = []
        for g in sorted(groups, key=lambda g: -g["span"])[:12]:
            worst.append(
                {
                    "span": round(g["span"], 3),
                    "nodes": sorted(
                        nodes[i].key if i != -1 else "coast"
                        for i in g["key"]
                    ),
                }
            )
        return {
            "junctions": len(groups),
            "max_span": round(max_span, 4),
            "p95_span": round(p95, 4),
            "median_span": round(med, 4),
            "max_spur": round(worst_spur, 4),
            "single_ring_groups": single_ring,
            "worst": worst,
        }

    jun_owner = _junction_metrics(borders_owner)
    jun_mid = _junction_metrics(borders_mid)

    # ------------------------------------------- coverage and fill dist
    t3 = time.perf_counter()
    coast_len = {
        nid: sum(a.length for a in arcs) for nid, arcs in coast_arcs.items()
    }

    def _coverage(border_map, len_getter):
        bad = []
        for nid, node in nodes.items():
            per = _perimeter(node.geom)
            blen = 0.0
            for nb in node.neighbours:
                pair = (min(nid, nb), max(nid, nb))
                blen += sum(len_getter(x) for x in border_map.get(pair, []))
            cov = (blen + coast_len.get(nid, 0.0)) / per if per else 1.0
            if abs(cov - 1.0) > 0.005:
                bad.append((node.key, round(cov * 100, 2)))
        return bad

    bad_cov_owner = _coverage(borders_owner, lambda a: a.length)
    bad_cov_mid = _coverage(borders_mid, lambda a: a.length)

    def _fill_metrics(border_map, pts_getter):
        leave = 0.0
        float_ = 0.0
        leave_at = float_at = None
        for (a, b), arcs in border_map.items():
            pts_list = [pts_getter(x) for x in arcs]
            if not pts_list:
                continue
            u = shapely.unary_union([nodes[a].geom, nodes[b].geom])
            edges = nodes[a].geom.boundary.union(nodes[b].geom.boundary)
            for pts in pts_list:
                lv = _sampled_max_dist([pts], u)
                fl = _sampled_max_dist([pts], edges)
                if lv > leave:
                    leave, leave_at = lv, (nodes[a].key, nodes[b].key)
                if fl > float_:
                    float_, float_at = fl, (nodes[a].key, nodes[b].key)
        return leave, leave_at, float_, float_at

    fill_owner = _fill_metrics(borders_owner, lambda a: a.pts)
    fill_mid = _fill_metrics(borders_mid, lambda a: a.pts)

    # Asymmetry of the owner method: the canonical line lies on side a;
    # the visible seam on side b is the distance to B's own edge.
    far_worst = (0.0, None)
    far_dists = []
    for (a, b), arcs in borders_owner.items():
        b_boundary = nodes[b].geom.boundary
        for arc in arcs:
            d = _sampled_max_dist([arc.pts], b_boundary, step=0.03)
            far_dists.append(d)
            if d > far_worst[0]:
                far_worst = (d, (nodes[a].key, nodes[b].key))
    far_dists.sort()
    far_stats = {
        "max": round(far_worst[0], 4),
        "at": far_worst[1],
        "p95": round(far_dists[int(len(far_dists) * 0.95)], 4),
        "median": round(far_dists[len(far_dists) // 2], 4),
    }

    # hover outline: assembled lines vs own ring, global max
    def _outline_fit(border_map, pts_getter):
        worst = (0.0, None)
        for nid, node in nodes.items():
            lines = [
                a.pts + ([a.pts[0]] if a.closed else [])
                for a in coast_arcs.get(nid, [])
            ]
            for nb in node.neighbours:
                pair = (min(nid, nb), max(nid, nb))
                lines += [
                    pts_getter(x) for x in border_map.get(pair, [])
                ]
            if not lines:
                continue
            mls = MultiLineString([p for p in lines if len(p) >= 2])
            if mls.is_empty:
                continue
            d = _sampled_max_dist(
                [
                    a.pts + ([a.pts[0]] if a.closed else [])
                    for a in coast_arcs.get(nid, [])
                ],
                node.geom.boundary,
            )
            # also: own ring to assembled lines
            boundary = node.geom.boundary
            segs = (
                list(boundary.geoms)
                if hasattr(boundary, "geoms")
                else [boundary]
            )
            ring_coords = []
            for seg in segs:
                ring_coords.extend(seg.segmentize(0.05).coords)
            arr = shapely.points(ring_coords)
            back = float(shapely.distance(arr, mls).max()) if len(arr) else 0.0
            w = max(d, back)
            if w > worst[0]:
                worst = (w, node.key)
        return worst

    fit_owner = _outline_fit(borders_owner, lambda a: a.pts)
    fit_mid = _outline_fit(borders_mid, lambda a: a.pts)
    t_metrics = time.perf_counter() - t3

    # ------------------------------------------------------------- sizes
    def _serialize(border_map, pts_getter):
        borders = {}
        for (a, b) in sorted(border_map):
            ds = "".join(
                _line_d(
                    [(round(x, 2), round(y, 2)) for x, y in pts_getter(it)]
                )
                for it in border_map[(a, b)]
            )
            if ds:
                borders[f"{a}_{b}"] = ds
        coasts = {
            str(nid): _arc_d(arcs) for nid, arcs in sorted(coast_arcs.items())
        }
        return borders, coasts

    ser = {}
    for name, bmap, getter in (
        ("owner", borders_owner, lambda a: a.pts),
        ("mid", borders_mid, lambda a: a.pts),
    ):
        borders, coasts = _serialize(bmap, getter)
        # layout B: own file
        body_b = {"borders": borders, "coasts": coasts}
        ver = hashlib.sha256(
            canonical_json(body_b).encode("utf-8")
        ).hexdigest()[:12]
        doc_b = canonical_json({"version": ver, **body_b}) + "\n"
        # layout A: inside geometry.json
        doc_a = canonical_json(
            {
                "outside": geometry["outside"],
                "paths": geometry["paths"],
                "sea_water": geometry["sea_water"],
                "borders": borders,
                "coasts": coasts,
                "version": geometry["version"],
            }
        ) + "\n"
        ser[name] = {
            "b_raw": len(doc_b.encode()),
            "b_gz": len(gzip.compress(doc_b.encode())),
            "a_raw": len(doc_a.encode()),
            "a_gz": len(gzip.compress(doc_a.encode())),
            "border_bytes": sum(len(v) for v in borders.values()),
            "coast_bytes": sum(len(v) for v in coasts.values()),
        }
        if name == method:
            ser["_doc_b"] = doc_b
    t4 = time.perf_counter()

    multi_part = sum(
        1
        for n in nodes.values()
        if isinstance(n.geom, MultiPolygon) and len(n.geom.geoms) > 1
    )

    report = {
        "params": {"eps": eps, "junc_r": JUNC_R, "mid_tol": MID_TOL,
                   "px_per_unit": PX_PER_UNIT},
        "counts": {
            "land_nodes": len(nodes),
            "multi_part_nodes": multi_part,
            "land_edges": len(land_edges),
            "land_edges_no_segment": len(stats["no_segment"]),
            "borders_under_0.05": len(stats["short_border"]),
            "b_side_missing": len(stats["b_side_missing"]),
        },
        "junctions": {
            "owner": jun_owner,
            "mid": jun_mid,
            "px_per_unit": PX_PER_UNIT,
        },
        "fill_vs_line": {
            "owner": {"leave_fill": fill_owner[0], "leave_at": fill_owner[1],
                      "off_edge": fill_owner[2], "off_edge_at": fill_owner[3]},
            "mid": {"leave_fill": fill_mid[0], "leave_at": fill_mid[1],
                    "off_edge": fill_mid[2], "off_edge_at": fill_mid[3]},
        },
        "owner_far_side": far_stats,
        "coverage": {
            "owner": {"bad_nodes": len(bad_cov_owner),
                      "worst": bad_cov_owner[:15]},
            "mid": {"bad_nodes": len(bad_cov_mid),
                    "worst": bad_cov_mid[:15]},
        },
        "outline_fit": {"owner": fit_owner, "mid": fit_mid},
        "sizes": ser,
        "no_segment": stats["no_segment"],
        "short_border": stats["short_border"],
        "b_side_missing": stats["b_side_missing"][:20],
        "runtime": {
            "load": round(t_load, 2),
            "label": round(t_label, 2),
            "lines": round(t_lines, 2),
            "metrics": round(t_metrics, 2),
            "serialize": round(t4 - t3 - t_metrics, 2),
            "total": round(t4 - t0, 2),
        },
    }
    return report, nodes, borders_owner, borders_mid, coast_arcs, manifest, geometry, ser


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tools.map_pipeline.borders_proto")
    ap.add_argument("--data-dir", default="data/map", type=Path)
    ap.add_argument(
        "--ref-dir", default="tools/map_pipeline/reference", type=Path
    )
    ap.add_argument("--eps", type=float, default=EPS)
    ap.add_argument("--method", choices=("owner", "mid"), default="owner")
    ap.add_argument("--skip-render", action="store_true")
    args = ap.parse_args(argv)

    (report, nodes, borders_owner, borders_mid, coast_arcs,
     manifest, geometry, ser) = run(args.data_dir, args.ref_dir, args.eps,
                                    args.method)

    state = _assign_states(nodes, None, manifest)

    ref = args.ref_dir
    ref.mkdir(parents=True, exist_ok=True)
    (ref / "borders_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    doc_b = ser.pop("_doc_b", None)
    if doc_b:
        (ref / "borders_layout_b.json").write_bytes(doc_b.encode("utf-8"))

    if not args.skip_render:
        from .html import write_preview
        from .render import render_crops

        border_map = (
            borders_owner if args.method == "owner" else borders_mid
        )
        write_preview(
            ref / "borders_preview.html", manifest, geometry, nodes,
            border_map, coast_arcs, state, args.method,
        )
        render_crops(
            ref, manifest, nodes, border_map, coast_arcs, state,
            args.method, CROPS,
        )
    print(json.dumps({
        "counts": report["counts"],
        "junctions": report["junctions"],
        "fill_vs_line": report["fill_vs_line"],
        "coverage": report["coverage"],
        "outline_fit": report["outline_fit"],
        "sizes": {k: {kk: vv for kk, vv in v.items() if kk != "doc_b"}
                  for k, v in report["sizes"].items()},
        "runtime": report["runtime"],
    }, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
