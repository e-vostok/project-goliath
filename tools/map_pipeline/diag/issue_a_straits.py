"""Issue A — missing strait crossings (Bosphorus, Dardanelles, Kerch).

Read-only diagnosis. Writes:
  reference/diag_strait_existing.tsv   — all strait edges in the manifest
  reference/diag_strait_candidates.tsv — LAND pairs with no land edge and
                                        polygon distance <= 1.5 u
  reference/diag_bosphorus.png, diag_dardanelles.png, diag_kerch.png —
                                        crops with node borders and edges
and prints the three named crossings in detail.
"""
from __future__ import annotations

import sys

from shapely import STRtree
from shapely.ops import nearest_points

from tools.map_pipeline.diag.common import (
    REF,
    edge_index,
    fmt_edge,
    load_geometry,
    load_manifest,
    node_geom,
    nodes_by_id,
    nodes_by_key,
    sea_name,
)
from tools.map_pipeline.diag.render import render_crop

MAX_GAP = 1.5


def _water_between(midpoint, sea_geoms, land_geoms, own_ids):
    """Name of the polygon under the gap midpoint (sea zone / land key)."""
    best = None
    for nid, geom in sea_geoms.items():
        d = geom.distance(midpoint)
        if d == 0:
            return ("sea", nid)
        if best is None or d < best[0]:
            best = (d, nid)
    for nid, geom in land_geoms.items():
        if nid in own_ids:
            continue
        if geom.distance(midpoint) == 0:
            return ("land", nid)
    if best is not None and best[0] <= 1.0:
        return ("sea", best[1])
    return ("none", None)


def main() -> None:
    manifest = load_manifest()
    geometry = load_geometry()
    by_id = nodes_by_id(manifest)
    by_key = nodes_by_key(manifest)
    edges = edge_index(manifest)

    land_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "LAND"]
    sea_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "SEA"]
    land_geoms = {i: node_geom(geometry, i) for i in land_ids}
    sea_geoms = {i: node_geom(geometry, i) for i in sea_ids}

    # ---- 1. existing strait edges -------------------------------------
    rows = []
    for e in manifest["edges"]:
        if e["type"] != "strait":
            continue
        a, b = by_id[e["a"]], by_id[e["b"]]
        rows.append(
            (
                e["a"], a["key"], a.get("name_ru") or "",
                e["b"], b["key"], b.get("name_ru") or "",
                e.get("name") or "",
                "" if e.get("multiplier") is None else e["multiplier"],
            )
        )
    with open(REF / "diag_strait_existing.tsv", "w", encoding="utf-8") as f:
        f.write("a_id\ta_key\ta_name_ru\tb_id\tb_key\tb_name_ru\tstrait_name\tmultiplier\n")
        for r in rows:
            f.write("\t".join(str(c) for c in r) + "\n")
    print(f"existing strait edges: {len(rows)} -> diag_strait_existing.tsv")

    # ---- 2. the three named crossings ---------------------------------
    pairs = [
        ("Bosphorus", "constantinople", "kocaeli", "diag_bosphorus.png"),
        ("Dardanelles", "dardanelles", "biga", "diag_dardanelles.png"),
        ("Kerch strait", "cafa", "taman", "diag_kerch.png"),
    ]
    for title, ka, kb, png in pairs:
        na, nb = by_key[ka], by_key[kb]
        ga, gb = land_geoms[na["id"]], land_geoms[nb["id"]]
        dist = ga.distance(gb)
        pair = (min(na["id"], nb["id"]), max(na["id"], nb["id"]))
        print(f"\n== {title}: {ka} ({na['id']}) <-> {kb} ({nb['id']})")
        print(f"   polygon distance: {dist:.3f} u (~{dist * 23:.0f} km)")
        print(f"   edge between them: {fmt_edge(edges.get(pair))}")
        for n in (na, nb):
            adj = [
                fmt_edge(e) + " -> " + by_id[e["b"] if e["a"] == n["id"] else e["a"]]["key"]
                for e in manifest["edges"]
                if n["id"] in (e["a"], e["b"])
            ]
            print(f"   {n['key']} edges: {sorted(adj)}")
        # land nodes in between: land nodes within 1.5u of either endpoint,
        # excluding each other and land-adjacent ones
        pa, pb = nearest_points(ga, gb)
        centre = type(pa)((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
        wm = _water_between(centre, sea_geoms, land_geoms, {na["id"], nb["id"]})
        print(f"   water between: {sea_name(by_id.get(wm[1])) if wm[0]=='sea' else wm}")
        near = []
        for nid in land_ids:
            if nid in (na["id"], nb["id"]):
                continue
            d = min(ga.distance(land_geoms[nid]), gb.distance(land_geoms[nid]))
            if d <= MAX_GAP:
                near.append((d, nid))
        near.sort()
        print("   land nodes within 1.5 u of an endpoint (possible stepping stones):")
        for d, nid in near:
            n = by_id[nid]
            ea = fmt_edge(edges.get((min(nid, na["id"]), max(nid, na["id"]))))
            eb = fmt_edge(edges.get((min(nid, nb["id"]), max(nid, nb["id"]))))
            print(f"     {n['key']} ({nid}, {n.get('name_ru') or ''}) "
                  f"dist {d:.3f} | edge to {ka}: {ea} | edge to {kb}: {eb}")
        # crop picture
        bbox = [
            min(ga.bounds[0], gb.bounds[0]) - 1.0,
            min(ga.bounds[1], gb.bounds[1]) - 1.0,
            max(ga.bounds[2], gb.bounds[2]) + 1.0,
            max(ga.bounds[3], gb.bounds[3]) + 1.0,
        ]
        crop_edges = [
            e for e in manifest["edges"]
            if e["a"] in land_geoms or e["a"] in sea_geoms
        ]
        # only edges with both endpoints' anchors inside the window
        crop_edges = [
            e
            for e in crop_edges
            if all(
                bbox[0] <= by_id[e[k]]["anchor"][0] <= bbox[2]
                and bbox[1] <= by_id[e[k]]["anchor"][1] <= bbox[3]
                for k in ("a", "b")
            )
        ]
        render_crop(
            REF / png,
            bbox,
            land_geoms,
            sea_geoms,
            by_id,
            crop_edges,
            highlight={na["id"]: (255, 210, 74), nb["id"]: (255, 210, 74)},
            label_ids={na["id"], nb["id"]},
            margin_u=0.3,
        )
        print(f"   crop -> {png}")

    # ---- 3. full candidate scan ---------------------------------------
    tree = STRtree(list(land_geoms.values()))
    id_list = list(land_geoms)
    out_rows = []
    counts = {"narrow": 0, "medium": 0, "wide": 0}
    for i, nid in enumerate(id_list):
        for j in tree.query(land_geoms[nid], predicate="dwithin", distance=MAX_GAP):
            oid = id_list[j]
            if oid <= nid:
                continue
            pair = (nid, oid)
            e = edges.get(pair)
            if e is not None and e["type"] == "land":
                continue
            d = land_geoms[nid].distance(land_geoms[oid])
            if d > MAX_GAP:
                continue
            pa, pb = nearest_points(land_geoms[nid], land_geoms[oid])
            mid = type(pa)((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)
            kind, wid = _water_between(
                mid, sea_geoms, land_geoms, {nid, oid}
            )
            water = (
                sea_name(by_id[wid]) if kind == "sea"
                else f"land:{by_id[wid]['key']}" if kind == "land" else "-"
            )
            cls = "narrow" if d <= 0.3 else "medium" if d <= 0.8 else "wide"
            counts[cls] += 1
            a, b = by_id[nid], by_id[oid]
            out_rows.append(
                (
                    a["key"], a.get("name_ru") or "",
                    b["key"], b.get("name_ru") or "",
                    f"{d:.3f}",
                    "none" if e is None else e["type"],
                    water,
                    cls,
                    f"{a['area']:.2f}", f"{b['area']:.2f}",
                )
            )
    out_rows.sort(key=lambda r: float(r[4]))
    with open(REF / "diag_strait_candidates.tsv", "w", encoding="utf-8") as f:
        f.write(
            "a_key\ta_name_ru\tb_key\tb_name_ru\tdistance_u\t"
            "existing_edge\twater_between\tclass\tarea_a\tarea_b\n"
        )
        for r in out_rows:
            f.write("\t".join(r) + "\n")
    print(f"\ncandidates <= {MAX_GAP} u: {len(out_rows)} "
          f"(narrow {counts['narrow']}, medium {counts['medium']}, "
          f"wide {counts['wide']}) -> diag_strait_candidates.tsv")


if __name__ == "__main__":
    sys.exit(main())
