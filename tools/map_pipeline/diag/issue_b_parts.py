"""Issue B — Леруик (northern_isles) is three island groups.

Read-only diagnosis. Writes:
  reference/diag_far_parts.tsv — every LAND node with >= 2 parts where the
      nearest inter-part distance is >= 3 u, or parts touch different sea
      zones
  reference/diag_leruik.png    — crop of the three groups with edges
and prints the full part/edge inventory of northern_isles.
"""
from __future__ import annotations

import sys

from shapely.geometry import Point

from tools.map_pipeline.diag.common import (
    REF,
    fmt_edge,
    load_geometry,
    load_manifest,
    node_geom,
    node_parts,
    nodes_by_id,
    nodes_by_key,
    sea_name,
)
from tools.map_pipeline.diag.render import render_crop

FAR_DISTANCE = 3.0
TOUCH_DISTANCE = 0.5  # part "touches" a sea zone if this close


def _seas_touched(part, sea_geoms, by_id):
    out = []
    for nid, geom in sea_geoms.items():
        if part.distance(geom) <= TOUCH_DISTANCE:
            out.append((part.distance(geom), sea_name(by_id[nid])))
    return {name for _, name in sorted(out)}


def main() -> None:
    manifest = load_manifest()
    geometry = load_geometry()
    by_id = nodes_by_id(manifest)
    by_key = nodes_by_key(manifest)

    sea_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "SEA"]
    sea_geoms = {i: node_geom(geometry, i) for i in sea_ids}

    # ---- 1. northern_isles inventory -----------------------------------
    node = by_key["northern_isles"]
    parts = node_parts(geometry, node["id"])
    anchor = Point(*node["anchor"])
    print(f"northern_isles ({node['id']}) parts: {len(parts)}, "
          f"anchor {node['anchor']}")
    for i, p in enumerate(parts):
        rp = p.representative_point()
        seas = _seas_touched(p, sea_geoms, by_id)
        print(
            f"  part {i}: area {p.area:.3f}, bbox "
            f"{[round(v, 2) for v in p.bounds]}, seas {sorted(seas)}, "
            f"repr_point ({rp.x:.2f}, {rp.y:.2f}), "
            f"anchor_inside={p.covers(anchor)}"
        )
    print("  edges:")
    for e in manifest["edges"]:
        if node["id"] in (e["a"], e["b"]):
            other = by_id[e["b"] if e["a"] == node["id"] else e["a"]]
            print(f"    {fmt_edge(e)} -> {other['key']} "
                  f"({other.get('name_ru') or ''})")

    # ---- 2. far-parts scan ---------------------------------------------
    rows = []
    for n in manifest["nodes"]:
        if n["kind"] != "LAND":
            continue
        ps = node_parts(geometry, n["id"])
        if len(ps) < 2:
            continue
        dists = [
            ps[i].distance(ps[j])
            for i in range(len(ps))
            for j in range(i + 1, len(ps))
        ]
        part_seas = [_seas_touched(p, sea_geoms, by_id) for p in ps]
        all_seas = set().union(*part_seas)
        differing = len({frozenset(s) for s in part_seas}) > 1
        if min(dists) >= FAR_DISTANCE or differing:
            areas = ",".join(f"{p.area:.2f}" for p in ps)
            rows.append(
                (
                    n["key"], n.get("name_ru") or "", len(ps),
                    f"{min(dists):.2f}", f"{max(dists):.2f}",
                    areas, ";".join(sorted(all_seas)),
                    "diff_seas" if differing else "",
                )
            )
    rows.sort(key=lambda r: -float(r[4]))
    with open(REF / "diag_far_parts.tsv", "w", encoding="utf-8") as f:
        f.write("key\tname_ru\tparts\tmin_part_dist_u\tmax_part_dist_u\t"
                "part_areas\tsea_zones\tflag\n")
        for r in rows:
            f.write("\t".join(str(c) for c in r) + "\n")
    print(f"\nfar-part nodes: {len(rows)} -> diag_far_parts.tsv")
    for r in rows:
        print("   ", r[0], r[1], f"parts={r[2]} min={r[3]} max={r[4]}",
              r[6], r[7])

    # ---- 3. crop --------------------------------------------------------
    all_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "LAND"]
    land_geoms = {i: node_geom(geometry, i) for i in all_ids}
    bbox = [534.0, 70.0, 566.0, 98.0]
    crop_edges = [
        e
        for e in manifest["edges"]
        if all(
            bbox[0] <= by_id[e[k]]["anchor"][0] <= bbox[2]
            and bbox[1] <= by_id[e[k]]["anchor"][1] <= bbox[3]
            for k in ("a", "b")
        )
    ]
    render_crop(
        REF / "diag_leruik.png",
        bbox,
        land_geoms,
        sea_geoms,
        by_id,
        crop_edges,
        ring_colors_for={node["id"]},
        label_ids={node["id"], by_key["sutherland"]["id"]},
        margin_u=0.3,
    )
    print("crop -> diag_leruik.png")


if __name__ == "__main__":
    sys.exit(main())
