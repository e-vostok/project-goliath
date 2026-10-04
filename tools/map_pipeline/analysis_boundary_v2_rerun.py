"""map_polish_2 Phase A (part 2) — in-memory rerun of the pipeline with the
proposed exclusions applied. Nothing is written to ``data/``.

Usage: ``python -m tools.map_pipeline.analysis_boundary_v2_rerun``
Prints: broken overrides references, ISOLATED_PART/sea-step errors the bare
exclusion would raise, zone-area deltas, connectivity leftovers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .analysis_boundary_v2 import DATA, OUT, load_geoms
from .errors import PipelineError, PipelineFailure
from .graph import build_graph
from .models import (
    Boundary,
    Overrides,
    collect_reference_errors,
    load_boundary,
    load_ids_lock,
    load_overrides,
)
from .pipeline import _apply_drop_parts, _check_isolated_parts, _select_nodes
from .pipeline_config_schema import load_pipeline_config
from .seas import build_seas, land_label_raster


def modified_inputs(excluded: set[str], boundary: Boundary,
                    overrides: Overrides, fix_refs: bool):
    """Return (boundary2, overrides2, removed_entries) after exclusion."""
    inc = [n for n in boundary.include if n not in excluded]
    exc = sorted(set(boundary.exclude_explicit) | excluded)
    boundary2 = Boundary.model_validate(
        {"include": inc, "exclude_explicit": exc}
    )
    ov = overrides.model_dump()
    excluded_keys = {n.lower() for n in excluded}
    removed = []
    if fix_refs:
        ov["drop_parts"] = [
            d for d in ov["drop_parts"] if d["key"] not in excluded_keys
        ]
        ov["straits"] = [
            s for s in ov["straits"]
            if s["a"] not in excluded_keys and s["b"] not in excluded_keys
        ]
        ov["edges_add"] = [
            e for e in ov["edges_add"]
            if e["a"] not in excluded_keys and e["b"] not in excluded_keys
        ]
        ov["edges_remove"] = [
            e for e in ov["edges_remove"]
            if e["a"] not in excluded_keys and e["b"] not in excluded_keys
        ]
    overrides2 = Overrides.model_validate(ov)
    return boundary2, overrides2, removed


def main() -> int:
    cfg = load_pipeline_config()
    boundary = load_boundary(DATA / "boundary.yaml")
    overrides = load_overrides(DATA / "overrides.yaml")
    lock = load_ids_lock(DATA / "ids.lock.json")
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))

    rows = json.loads((OUT / "red_fractions.json").read_text(encoding="utf-8"))
    excluded = {
        r["name"] for r in rows
        if r["decided"] or (r["frac"] or 0) >= 0.50
    }
    print(f"proposed exclusions: {len(excluded)}")

    paths, geoms = load_geoms(DATA, cfg)

    # --- (b) overrides entries that the bare exclusion breaks
    boundary2, ov2, _ = modified_inputs(excluded, boundary, overrides,
                                        fix_refs=False)
    ref_errors = collect_reference_errors(overrides, boundary2)
    print("\n== collect_reference_errors after exclusion ==")
    for e in ref_errors:
        print("  ", e.code, e.message)

    # --- ISOLATED_PART / sea errors on the bare exclusion (with refs fixed)
    boundary2, ov2, _ = modified_inputs(excluded, boundary, overrides,
                                        fix_refs=True)
    nodes2, info2 = _select_nodes(paths, boundary2, ov2)
    for node in nodes2.values():
        node.parts = geoms[node.source_name]
    applied = _apply_drop_parts(nodes2, ov2)
    try:
        _check_isolated_parts(nodes2, geoms, boundary2, ov2, cfg)
        print("\nisolated parts: none")
    except PipelineFailure as f:
        print("\n== ISOLATED_PART ==")
        for e in f.errors:
            print("  ", e.message)

    try:
        sea2 = build_seas(nodes2, geoms, ov2, cfg)
    except PipelineFailure as f:
        print("\n== build_seas errors ==")
        for e in f.errors:
            print("  ", e.code, e.message)
        sea2 = None

    if sea2 is not None:
        # (c) zone area deltas vs manifest SEA areas
        old_area = {
            n["key"]: n["area"] for n in manifest["nodes"]
            if n["kind"] == "SEA"
        }
        print("\n== zone area deltas (old -> new) ==")
        for z, key in enumerate(sea2.zone_keys, start=1):
            new = sea2.zone_areas[z - 1]
            old = old_area.get(key, 0.0)
            if abs(new - old) > 0.01:
                pct = 100 * (new - old) / old if old else 0
                print(f"  {key:22s} {old:9.2f} -> {new:9.2f}  ({pct:+.1f}%)")

        # --- full graph on the new world
        ids = dict(lock.ids)
        ordered = sorted(nodes2, key=lambda k: ids[k])
        land_labels = land_label_raster(
            [nodes2[k] for k in ordered], sea2.land, sea2.frame
        )
        try:
            graph = build_graph(nodes2, sea2, ids, ov2, cfg, land_labels)
        except PipelineFailure as f:
            print("\n== build_graph errors ==")
            for e in f.errors:
                print("  ", e.code, e.message)
                for d in e.details:
                    print("     ", d)
            graph = None

        if graph is not None:
            # (3a) coast/sea edges the two retired zones would lose
            for zk in ("sea_atl_africa", "sea_iceland"):
                zi = sea2.zone_keys.index(zk) + 1
                node = next(
                    n for n in graph.nodes
                    if n.zone_index == zi and n.kind == "SEA"
                )
                edges = [
                    e for e in graph.edges if e.a == node.id or e.b == node.id
                ]
                print(f"\n== {zk} id={node.id} area="
                      f"{round(node.area, 2)} ==")
                by_id = {n.id: n for n in graph.nodes}
                for e in edges:
                    other = by_id[e.b if e.a == node.id else e.a]
                    print(f"   {e.type:6s} -> {other.key} ({other.kind})")

            # (3a-ii) zones with no coast edge to remaining land
            print("\n== zones with no coast edge to playable land ==")
            sea_nodes = [n for n in graph.nodes if n.kind == "SEA"]
            for sn in sea_nodes:
                has_coast = any(
                    e.type == "coast"
                    for e in graph.edges
                    if e.a == sn.id or e.b == sn.id
                )
                if not has_coast:
                    print(f"  {sn.key} (area {round(sn.area, 2)})")

            # connectivity after additionally removing retired zones
            print("\n== connectivity check, retired zones removed ==")
            retired_keys = {"sea_atl_africa", "sea_iceland"}
            gnodes = [n for n in graph.nodes if n.key not in retired_keys]
            gids = {n.id for n in gnodes}
            gedges = [
                e for e in graph.edges if e.a in gids and e.b in gids
            ]
            parent = {n.id: n.id for n in gnodes}

            def find(x):
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for e in gedges:
                ra, rb = find(e.a), find(e.b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            comps: dict[int, list] = {}
            for n in gnodes:
                comps.setdefault(find(n.id), []).append(n.key)
            groups = sorted(comps.values(), key=lambda c: (-len(c), c[0]))
            print(f"   components: {len(groups)}")
            for gcomp in groups[1:]:
                print("   stray component:", gcomp)
            print("   connected w/o manual+straits:", end=" ")
            real = [
                e for e in gedges
                if e.type != "strait" and not e.manual
            ]
            parent = {n.id: n.id for n in gnodes}
            for e in real:
                ra, rb = find(e.a), find(e.b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
            roots = {find(n.id) for n in gnodes}
            print(len(roots) == 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
