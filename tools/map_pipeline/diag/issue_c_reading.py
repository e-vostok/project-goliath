"""Issue C — Рединг (berkshire) outline shows two lobes with a seam.

Read-only diagnosis. Writes:
  reference/diag_reading.png      — crop at 40 px/u, each ring in its own
                                    colour with vertex dots
  reference/diag_seam_nodes.tsv   — every LAND node where two parts share a
      near-coincident boundary run (an internal seam that the selection
      stroke draws as a line)
and prints the ring inventory + source-tracing facts for berkshire.
"""
from __future__ import annotations

import re
import sys

from tools.map_pipeline.diag.common import (
    DATA,
    REF,
    fmt_edge,
    load_geometry,
    load_manifest,
    node_geom,
    node_parts,
    nodes_by_id,
    nodes_by_key,
)
from tools.map_pipeline.diag.render import render_crop

SEAM_EPS = 0.03  # boundaries closer than this count as coincident
SEAM_MIN_LEN = 0.05  # shared run must be at least this long


def _seam_len(a, b) -> float:
    """Length of b's boundary that runs within SEAM_EPS of a's boundary."""
    inter = b.boundary.intersection(a.boundary.buffer(SEAM_EPS))
    return inter.length


def main() -> None:
    manifest = load_manifest()
    geometry = load_geometry()
    by_id = nodes_by_id(manifest)
    by_key = nodes_by_key(manifest)

    node = by_key["berkshire"]
    parts = node_parts(geometry, node["id"])
    print(f"berkshire ({node['id']}) parts: {len(parts)}")
    for i, p in enumerate(parts):
        print(f"  ring {i}: area {p.area:.3f}, bbox "
              f"{[round(v, 2) for v in p.bounds]}, holes "
              f"{len(p.interiors)}, vertices {len(p.exterior.coords) - 1}")
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a, b = parts[i], parts[j]
            print(
                f"  rings {i}/{j}: distance {a.distance(b):.4f}, "
                f"overlap area {a.intersection(b).area:.4f}, "
                f"seam length {max(_seam_len(a, b), _seam_len(b, a)):.3f}"
            )
    # neighbour overlap check
    for e in manifest["edges"]:
        if node["id"] in (e["a"], e["b"]) and e["type"] == "land":
            oid = e["b"] if e["a"] == node["id"] else e["a"]
            other = node_geom(geometry, oid)
            ov = sum(p.intersection(other).area for p in parts)
            print(f"  overlap with neighbour {by_id[oid]['key']}: {ov:.4f}")

    # source: how many subpaths does the Berkshire path have?
    src = (DATA / "source" / "map.svg").read_text(encoding="utf-8")
    d = re.search(r'<path id="Berkshire"[^>]*d="([^"]+)"', src).group(1)
    subs = len(re.findall(r"[Mm]\s*-?[\d.]", d))
    print(f"  source map.svg path 'Berkshire': {subs} subpaths")
    # any overrides merge/patch touching berkshire?
    ov = (DATA / "overrides.yaml").read_text(encoding="utf-8")
    print("  overrides mentions 'berkshire' outside names_ru:",
          [ln for ln in ov.splitlines()
           if "berkshire" in ln and "Рединг" not in ln])

    # crop picture at 40 px/u
    sea_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "SEA"]
    land_ids = [n["id"] for n in manifest["nodes"] if n["kind"] == "LAND"]
    land_geoms = {i: node_geom(geometry, i) for i in land_ids}
    sea_geoms = {i: node_geom(geometry, i) for i in sea_ids}
    bbox = list(node["bbox"])
    crop_edges = [
        e
        for e in manifest["edges"]
        if all(
            bbox[0] - 1.5 <= by_id[e[k]]["anchor"][0] <= bbox[2] + 1.5
            and bbox[1] - 1.5 <= by_id[e[k]]["anchor"][1] <= bbox[3] + 1.5
            for k in ("a", "b")
        )
    ]
    render_crop(
        REF / "diag_reading.png",
        bbox,
        land_geoms,
        sea_geoms,
        by_id,
        crop_edges,
        ring_colors_for={node["id"]},
        vertex_dots_for={node["id"]},
        label_ids={node["id"]},
        margin_u=0.8,
        scale=40.0,
    )
    print("crop -> diag_reading.png")

    # seam scan over all LAND nodes
    rows = []
    for n in manifest["nodes"]:
        if n["kind"] != "LAND":
            continue
        ps = node_parts(geometry, n["id"])
        if len(ps) < 2:
            continue
        best = 0.0
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                best = max(
                    best, _seam_len(ps[i], ps[j]), _seam_len(ps[j], ps[i])
                )
        if best >= SEAM_MIN_LEN:
            rows.append(
                (
                    n["key"], n.get("name_ru") or "", len(ps),
                    f"{best:.3f}",
                )
            )
    rows.sort(key=lambda r: -float(r[3]))
    with open(REF / "diag_seam_nodes.tsv", "w", encoding="utf-8") as f:
        f.write("key\tname_ru\tparts\tseam_len_u\n")
        for r in rows:
            f.write("\t".join(str(c) for c in r) + "\n")
    print(f"seam nodes: {len(rows)} -> diag_seam_nodes.tsv")


if __name__ == "__main__":
    sys.exit(main())
