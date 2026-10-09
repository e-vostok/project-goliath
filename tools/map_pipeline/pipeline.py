"""Pipeline contract steps (Spec, Appendix A): select the game field,
drop/keep listed parts, detect isolated parts, assign stable ids, build sea
zones and the node graph.

Deterministic by construction: sorted iteration everywhere, no timestamps, no
randomness — identical inputs produce byte-identical outputs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from lxml import etree
from shapely import STRtree
from shapely.geometry import MultiPolygon, Point, Polygon, box

from .errors import (
    BOUNDARY_UNKNOWN_ID,
    DATA_INVALID,
    DROP_PART_EMPTIES_PROVINCE,
    DROP_PART_NOT_FOUND,
    GEOMETRY_TOO_LARGE,
    ISOLATED_PART,
    KEY_COLLISION,
    KEY_INVALID,
    VIEWBOX_MISMATCH,
    PipelineError,
    PipelineFailure,
)
from .geometry import (
    _polygon_list,
    _vertex_count,
    build_bay_region,
    build_land_geometries,
    build_land_mask,
    build_lake_region,
    build_outside,
    build_sea_geometries,
    node_metrics,
)
from .graph import KIND_SEA, build_graph
from .ids import assign_ids
from .manifest import (
    build_inputs_sha256,
    build_manifest,
    dumps_manifest,
    playable_bbox,
)
from .manifest_schema import validate_manifest
from .models import (
    Boundary,
    Overrides,
    collect_reference_errors,
    load_boundary,
    load_overrides,
)
from .patches import apply_geometry_patches
from .pipeline_config_schema import PipelineConfig, load_pipeline_config
from .preview import render_map_preview, render_preview
from .seas import SeaRaster, build_seas, land_label_raster
from .svg_source import build_geometries, read_province_paths, safe_union
from .svgpath import build_geometry_doc, dumps, parse_path

_KEY_RE = re.compile(r"^[a-z0-9_]+$")

# Small buffer so a listed point sitting exactly on a cleaned border still
# selects its polygon part.
POINT_IN_PART_BUFFER = 0.01

_SOURCE_FILE = "source/map.svg"
_BOUNDARY_FILE = "boundary.yaml"
_OVERRIDES_FILE = "overrides.yaml"
_IDS_LOCK_FILE = "ids.lock.json"


@dataclass
class _Node:
    key: str
    source_name: str
    parts: list[Polygon] = field(default_factory=list)
    # map2_10: renames give a display ``name`` other than the slugged
    # source name; ``source_name`` itself never changes.
    display_name: str | None = None


@dataclass
class _Prep:
    """Result of the shared steps 1–3 used by both commands."""

    cfg: PipelineConfig
    boundary: Boundary
    overrides: Overrides
    paths: dict[str, str]
    nodes: dict[str, _Node]
    geoms: dict[str, list[Polygon]]
    info: list[str]
    applied_drops: list[tuple[str, float]]


def _point_in_part(part: Polygon, point: tuple[float, float]) -> bool:
    return part.buffer(POINT_IN_PART_BUFFER).contains(Point(point))


def _select_nodes(
    paths: dict[str, str], boundary: Boundary, overrides: Overrides
) -> tuple[dict[str, _Node], list[str]]:
    """Apply boundary include + technical_exclude; assign slugs.

    Returns the node table keyed by slug and the list of INFO report lines.
    Raises ``PipelineFailure`` for unknown names, bad or colliding keys.
    """
    errors: list[PipelineError] = []
    for name in boundary.include:
        if name not in paths:
            errors.append(
                PipelineError(
                    BOUNDARY_UNKNOWN_ID,
                    f"boundary include name {name!r} not found among "
                    "source province ids",
                )
            )
    if errors:
        raise PipelineFailure(errors)

    tech_exclude = set(overrides.technical_exclude)
    include_keys = {n.lower() for n in boundary.include}
    info = [
        f"technical_exclude entry {key!r} is not among boundary include "
        "keys; ignored"
        for key in sorted(tech_exclude - include_keys)
    ]

    effective = sorted(
        n for n in boundary.include if n.lower() not in tech_exclude
    )
    by_key: dict[str, list[str]] = {}
    for name in effective:
        key = name.lower()
        if not _KEY_RE.match(key):
            errors.append(
                PipelineError(
                    KEY_INVALID,
                    f"source name {name!r} yields invalid key {key!r}",
                )
            )
            continue
        by_key.setdefault(key, []).append(name)
    for key in sorted(by_key):
        names = by_key[key]
        if len(names) > 1:
            errors.append(
                PipelineError(
                    KEY_COLLISION,
                    f"source names {names} map to the same key {key!r}",
                )
            )
    if errors:
        raise PipelineFailure(errors)

    nodes = {
        key: _Node(key=key, source_name=names[0])
        for key, names in by_key.items()
    }
    # map2_10: declared renames rewrite key and display name; the id
    # follows through ``assign_ids`` (previous_keys in the lock).
    for r in overrides.renames:
        node = nodes.get(r.from_key)
        if node is None:
            continue  # already reported by collect_reference_errors
        del nodes[r.from_key]
        node.key = r.to_key
        node.display_name = r.name
        nodes[r.to_key] = node
        info.append(f"renames: {r.from_key} -> {r.to_key} ({r.name})")
    return nodes, info


def _apply_drop_parts(
    nodes: dict[str, _Node], overrides: Overrides
) -> list[tuple[str, float]]:
    """Remove parts listed in ``drop_parts``; return applied (key, area)."""
    errors: list[PipelineError] = []
    applied: list[tuple[str, float]] = []
    claimed: set[tuple[str, int]] = set()
    for entry in overrides.drop_parts:
        node = nodes.get(entry.key)
        hit = None
        if node is not None:
            for i, part in enumerate(node.parts):
                if _point_in_part(part, entry.point.as_tuple()):
                    hit = i
                    break
        if hit is None:
            errors.append(
                PipelineError(
                    DROP_PART_NOT_FOUND,
                    f"drop_parts point {entry.point.as_tuple()} matches no "
                    f"part of {entry.key!r}",
                )
            )
            continue
        if (entry.key, hit) in claimed:
            errors.append(
                PipelineError(
                    DATA_INVALID,
                    f"two drop_parts entries select the same part of "
                    f"{entry.key!r}",
                )
            )
            continue
        claimed.add((entry.key, hit))
        applied.append((entry.key, node.parts[hit].area))
    if errors:
        raise PipelineFailure(errors)

    per_key: dict[str, set[int]] = {}
    for key, idx in claimed:
        per_key.setdefault(key, set()).add(idx)
    emptied: list[PipelineError] = []
    for key in sorted(per_key):
        node = nodes[key]
        node.parts = [
            p for i, p in enumerate(node.parts) if i not in per_key[key]
        ]
        if not node.parts:
            emptied.append(
                PipelineError(
                    DROP_PART_EMPTIES_PROVINCE,
                    f"drop_parts removes every part of {key!r}",
                )
            )
    if emptied:
        raise PipelineFailure(emptied)
    return applied


def _check_isolated_parts(
    nodes: dict[str, _Node],
    geoms: dict[str, list[Polygon]],
    boundary: Boundary,
    overrides: Overrides,
    cfg: PipelineConfig,
) -> None:
    """Flag parts whose neighbourhood holds no included province.

    A part is a violation when at least one *other* source province (technical
    exclusions ignored) intersects its ``isolated.neighbour_buffer`` zone and
    none of those neighbours is an included province. Parts smaller than
    ``isolated.min_part_area``, parts with no neighbours at all and parts
    whitelisted via ``keep_parts`` are fine. Every violation is reported.
    """
    all_parts: list[Polygon] = []
    owner: list[str] = []
    for name in sorted(geoms):
        for part in geoms[name]:
            all_parts.append(part)
            owner.append(name)
    tree = STRtree(all_parts)

    tech_exclude = set(overrides.technical_exclude)
    included_names = set(boundary.include)
    keep_points: dict[str, list[tuple[float, float]]] = {}
    for entry in overrides.keep_parts:
        keep_points.setdefault(entry.key, []).append(entry.point.as_tuple())

    errors: list[PipelineError] = []
    for key in sorted(nodes):
        node = nodes[key]
        for part in node.parts:
            if part.area < cfg.isolated.min_part_area:
                continue
            zone = part.buffer(cfg.isolated.neighbour_buffer)
            neighbours = {
                owner[i]
                for i in tree.query(zone, predicate="intersects")
            } - {node.source_name}
            neighbours = {
                n for n in neighbours if n.lower() not in tech_exclude
            }
            if not neighbours or neighbours & included_names:
                continue
            if any(
                _point_in_part(part, pt) for pt in keep_points.get(key, [])
            ):
                continue
            rp = part.representative_point()
            errors.append(
                PipelineError(
                    ISOLATED_PART,
                    f"key={key} point=({round(rp.x, 2)}, "
                    f"{round(rp.y, 2)}) area={round(part.area, 2)} "
                    f"neighbours={sorted(neighbours)}",
                )
            )
    if errors:
        raise PipelineFailure(errors)


def _write_text(path: Path, text: str) -> None:
    """Write generated text as raw UTF-8 bytes (LF endings only).

    ``Path.write_text`` would translate ``\\n`` to CRLF on Windows, which
    breaks byte-determinism and ``--check`` on hosts with
    ``core.autocrlf=true``. Generated files always carry LF bytes; git
    normalisation handles the worktree copy.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _read_text_normalized(path: Path) -> str:
    """Read a generated text file with EOL normalisation (CRLF -> LF)."""
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def _prepare(data_dir: Path) -> _Prep:
    """Shared steps 1–3: load inputs, select nodes, apply drop_parts."""
    cfg = load_pipeline_config()
    boundary = load_boundary(data_dir / _BOUNDARY_FILE)
    overrides = load_overrides(data_dir / _OVERRIDES_FILE)
    ref_errors = collect_reference_errors(overrides, boundary)
    if ref_errors:
        raise PipelineFailure(ref_errors)

    paths = read_province_paths(data_dir / _SOURCE_FILE)
    nodes, info = _select_nodes(paths, boundary, overrides)
    geoms = build_geometries(paths, cfg.clean)
    # Step 3a (Spec 1.9): manual geometry patches act on the cleaned source
    # geometry before the boundary filter — the donated side may be an
    # excluded province (e.g. Buhayra's coastal notch -> Alexandria).
    geoms, patch_info, additions = apply_geometry_patches(geoms, overrides)
    info.extend(patch_info)
    # A ``split`` patch adds a node that has no boundary.yaml entry: the new
    # province exists only in patched ``geoms`` under its source-style name.
    for key, name in additions:
        nodes[key] = _Node(key=key, source_name=name)
    for node in nodes.values():
        node.parts = geoms[node.source_name]

    applied = _apply_drop_parts(nodes, overrides)
    _check_isolated_parts(nodes, geoms, boundary, overrides, cfg)
    return _Prep(cfg, boundary, overrides, paths, nodes, geoms, info, applied)


def _sea_keys(overrides: Overrides) -> list[str]:
    return [z.key for z in overrides.sea_zones]


def _renames_map(overrides: Overrides) -> dict[str, str]:
    return {r.from_key: r.to_key for r in overrides.renames}


def _lock_keep_extra(boundary: Boundary) -> set[str]:
    """Keys that may stay in ``ids.lock.json`` without producing a node.

    1.9: provinces moved to ``boundary.exclude_explicit`` and retired sea
    zones keep their ids forever (they are the retired-node set the backend
    synchronises against). Retired sea keys are already in ``_sea_keys``;
    only the excluded-land slugs are extra.
    """
    return {name.lower() for name in boundary.exclude_explicit}


def _build_nodes_report(
    source_path_count: int,
    boundary: Boundary,
    nodes: dict[str, _Node],
    applied_drops: list[tuple[str, float]],
    info: list[str],
    new_id_range: tuple[int, int] | None,
) -> str:
    multi = sum(1 for n in nodes.values() if len(n.parts) > 1)
    lines = [
        "# map_pipeline — nodes report",
        "",
        f"- Source province paths: {source_path_count}",
        f"- Boundary include names: {len(boundary.include)}",
        f"- Land nodes: {len(nodes)}",
        f"- Multi-part provinces: {multi}",
        f"- drop_parts applied: {len(applied_drops)}",
    ]
    for key, area in sorted(applied_drops):
        lines.append(f"  - `{key}`: removed part area {round(area, 2)}")
    if new_id_range is None:
        lines.append("- New ids assigned: none")
    else:
        lines.append(f"- New ids assigned: {new_id_range[0]}..{new_id_range[1]}")
    lines.append("")
    lines.append("## INFO")
    lines.extend(f"- {item}" for item in info)
    lines.append("")
    return "\n".join(lines)


def _write_nodes_outputs(
    data_dir: Path,
    out_dir: Path,
    prep: _Prep,
    ids: dict[str, int],
    new_ids: list[int],
    lock_text: str,
    lock_changed: bool,
) -> None:
    """ids.lock.json (if changed), land_nodes.json and report.md."""
    if lock_changed:
        _write_text(data_dir / _IDS_LOCK_FILE, lock_text)

    records = [
        {
            "id": ids[node.key],
            "key": node.key,
            "source_name": node.source_name,
            "parts": len(node.parts),
            "area": round(sum(p.area for p in node.parts), 4),
        }
        for node in prep.nodes.values()
    ]
    records.sort(key=lambda r: r["id"])
    _write_text(
        out_dir / "land_nodes.json",
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
    )

    new_id_range = (new_ids[0], new_ids[-1]) if new_ids else None
    _write_text(
        out_dir / "report.md",
        _build_nodes_report(
            len(prep.paths), prep.boundary, prep.nodes,
            prep.applied_drops, prep.info, new_id_range,
        ),
    )


def run_nodes(data_dir: Path, out_dir: Path, check: bool = False) -> int:
    """Run steps 1–4. Returns the process exit code (0 ok / 1 failure)."""
    prep = _prepare(data_dir)
    ids, new_ids, lock_text, lock_changed = assign_ids(
        data_dir, sorted(prep.nodes), _sea_keys(prep.overrides),
        _lock_keep_extra(prep.boundary),
        renames=_renames_map(prep.overrides),
    )
    if check:
        return 1 if lock_changed else 0
    _write_nodes_outputs(
        data_dir, out_dir, prep, ids, new_ids, lock_text, lock_changed
    )
    return 0


def _graph_json(graph) -> str:
    nodes = [
        {
            "id": n.id,
            "key": n.key,
            "kind": n.kind,
            "name": n.name,
            "name_ru": n.name_ru,
            "area": round(n.area, 2) if n.kind == "SEA" else round(n.area, 4),
        }
        for n in graph.nodes
    ]
    edges = []
    for e in graph.edges:
        rec = {
            "a": e.a,
            "b": e.b,
            "type": e.type,
            "len": None if e.len is None else round(e.len, 3),
        }
        if e.type == "strait":
            rec["name"] = e.name
            rec["multiplier"] = e.multiplier
        edges.append(rec)
    return (
        json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False,
                   indent=2)
        + "\n"
    )


def _sea_raster_json(sea: SeaRaster) -> str:
    f = sea.frame
    doc = {
        "frame": [f.x0, f.y0, f.x1, f.y1],
        "pixels_per_unit": f.r,
        "width": f.width,
        "height": f.height,
        "zone_keys": sea.zone_keys,
        "pixel_convention": (
            "pixel (col,row) has its centre at (x0 + col/r, y0 + row/r); "
            "a point (x,y) maps to pixel "
            "(round((x-x0)*r), round((y-y0)*r))"
        ),
    }
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _build_graph_report(prep: _Prep, sea: SeaRaster, graph) -> str:
    cfg = prep.cfg
    by_id = {n.id: n for n in graph.nodes}
    neighbours: dict[int, set[int]] = {n.id: set() for n in graph.nodes}
    for e in graph.edges:
        neighbours[e.a].add(e.b)
        neighbours[e.b].add(e.a)

    by_type: dict[str, int] = {}
    for e in graph.edges:
        by_type[e.type] = by_type.get(e.type, 0) + 1
    manual = sum(1 for e in graph.edges if e.manual)
    straits = by_type.get("strait", 0)
    land_count = sum(1 for n in graph.nodes if n.kind == "LAND")

    lines = [
        "# map_pipeline — graph report",
        "",
        f"- Land nodes: {land_count}",
        f"- Sea zones: {len(sea.zone_keys) - len(sea.retired)}"
        + (
            f" (+{len(sea.retired)} retired)"
            if sea.retired
            else ""
        ),
        f"- Edges total: {len(graph.edges)}",
    ]
    for t in ("land", "coast", "sea", "strait"):
        lines.append(f"  - {t}: {by_type.get(t, 0)}")
    lines.append(f"- Manual edges applied (edges_add): {manual}")
    lines.append(f"- Straits applied: {straits}")
    lines.append(
        "- Graph stays connected without straits and manual edges: "
        + ("yes" if graph.connected_no_manual else "NO")
    )

    lines += ["", "## Sea zones", ""]
    lines.append("| # | key | name_ru | area | seeds | neighbours |")
    lines.append("| - | --- | ------- | ---- | ----- | ---------- |")
    seeds_per_zone: dict[str, int] = {}
    for z in prep.overrides.sea_zones:
        seeds_per_zone[z.key] = len(z.seeds)
    for z, key in enumerate(sea.zone_keys, start=1):
        node = next(
            (
                n
                for n in graph.nodes
                if n.zone_index == z and n.kind == "SEA"
            ),
            None,
        )
        lines.append(
            f"| {z} | {key} | {sea.zone_name_ru[z - 1]} | "
            f"{round(sea.zone_areas[z - 1], 2)} | {seeds_per_zone[key]} | "
            + ("retired" if node is None else str(len(neighbours[node.id])))
            + " |"
        )

    lines += ["", "## Snapped seeds", ""]
    if not sea.snapped:
        lines.append("- none")
    for s in sea.snapped:
        flag = " (already claimed — skipped)" if s.claimed else ""
        lines.append(
            f"- `{s.zone_key}` ({s.point[0]}, {s.point[1]}) -> "
            f"pixel {s.pixel}, distance {round(s.distance, 3)} units{flag}"
        )

    lines += ["", "## Small water bodies (Spec 3.2 step 5a)", ""]
    lines.append(
        f"- Lakes: {len(sea.lakes)}, total area "
        f"{round(sum(l.area for l in sea.lakes), 2)}"
    )
    lines.append(
        f"- Bays: {len(sea.bays)}, total area "
        f"{round(sum(b.area for b in sea.bays), 2)}"
    )
    biggest = sorted(sea.lakes, key=lambda l: -l.area)[
        : cfg.report.largest_lakes
    ]
    for lake in biggest:
        lines.append(
            f"  - largest lake area {round(lake.area, 2)}, centroid "
            f"({round(lake.centroid[0], 2)}, {round(lake.centroid[1], 2)})"
        )
    all_small = sorted(
        [*sea.lakes, *sea.bays],
        key=lambda l: (round(l.centroid[1], 2), round(l.centroid[0], 2)),
    )
    if all_small:
        lines.append("")
        lines.append("| area | class | dist to sea | centroid | note |")
        lines.append("| ---- | ----- | ----------- | -------- | ---- |")
        for rec in all_small:
            dist = (
                "inf"
                if rec.sea_distance == float("inf")
                else f"{rec.sea_distance:.2f}"
            )
            lines.append(
                f"| {round(rec.area, 2)} | "
                f"{'bay' if rec.bay else 'lake'} | {dist} | "
                f"({round(rec.centroid[0], 2)}, "
                f"{round(rec.centroid[1], 2)}) | {rec.forced or ''} |"
            )

    lines += ["", "## water_outside", ""]
    if not sea.water_outside:
        lines.append("- none matched")
    for name, area in sea.water_outside:
        lines.append(f"- {name}: component area {round(area, 2)}")

    lines += ["", "## Unreached band pieces", ""]
    lines.append(
        f"- {sea.unreached_small_count} pieces below lake_max_area, "
        f"total area {round(sea.unreached_small_area, 2)}"
    )

    lines += ["", "## Anomalies", ""]
    flagged = 0
    for n in graph.nodes:
        deg = len(neighbours[n.id])
        if n.kind == "LAND" and deg >= cfg.report.land_degree_warn:
            lines.append(
                f"- land node `{n.key}` has {deg} neighbours "
                f"(>= {cfg.report.land_degree_warn})"
            )
            flagged += 1
        if n.area < cfg.report.small_area_warn:
            lines.append(
                f"- node `{n.key}` area {round(n.area, 4)} "
                f"< {cfg.report.small_area_warn}"
            )
            flagged += 1
        if n.kind == "SEA" and deg < 3:
            lines.append(
                f"- sea zone `{n.key}` has only {deg} neighbours"
            )
            flagged += 1
    if not flagged:
        lines.append("- none")

    # Report-only check (Spec 1.9): active zones expected to carry at least
    # one coast edge to playable land; retired zones are listed separately.
    coasted: set[int] = set()
    for e in graph.edges:
        if e.type == "coast":
            if by_id[e.a].kind == "SEA":
                coasted.add(e.a)
            if by_id[e.b].kind == "SEA":
                coasted.add(e.b)
    coastless = [
        n for n in graph.nodes if n.kind == "SEA" and n.id not in coasted
    ]
    lines += ["", "## Sea zones without a coast edge to playable land", ""]
    if not coastless:
        lines.append("- none")
    for n in coastless:
        lines.append(f"- `{n.key}` (id {n.id}) — active, no coast edge")
    if sea.retired:
        for key in sorted(sea.retired):
            lines.append(f"- `{key}` — retired (no node)")
    lines.append("")

    lines += ["## Islands (land nodes whose neighbours are all SEA)", ""]
    islands = [
        n
        for n in graph.nodes
        if n.kind == "LAND"
        and neighbours[n.id]
        and all(by_id[i].kind == "SEA" for i in neighbours[n.id])
    ]
    if not islands:
        lines.append("- none")
    for n in islands:
        zones = ", ".join(
            sorted(by_id[i].key for i in neighbours[n.id])
        )
        lines.append(
            f"- `{n.key}` (area {round(n.area, 2)}): {zones}"
        )
    lines.append("")

    all_info = prep.info + graph.info
    if all_info:
        lines += ["## INFO", ""]
        lines.extend(f"- {item}" for item in all_info)
        lines.append("")
    return "\n".join(lines)


def run_graph(
    data_dir: Path, out_dir: Path, check: bool = False,
    preview: bool = True,
) -> int:
    """Run steps 1–6. Returns the process exit code (0 ok / 1 failure)."""
    prep = _prepare(data_dir)
    sea = build_seas(prep.nodes, prep.geoms, prep.overrides, prep.cfg)
    ids, new_ids, lock_text, lock_changed = assign_ids(
        data_dir, sorted(prep.nodes), _sea_keys(prep.overrides),
        _lock_keep_extra(prep.boundary),
        renames=_renames_map(prep.overrides),
    )
    ordered = sorted(prep.nodes, key=lambda k: ids[k])
    land_labels = land_label_raster(
        [prep.nodes[k] for k in ordered], sea.land, sea.frame
    )
    graph = build_graph(
        prep.nodes, sea, ids, prep.overrides, prep.cfg, land_labels
    )

    if check:
        return 1 if lock_changed else 0

    _write_nodes_outputs(
        data_dir, out_dir, prep, ids, new_ids, lock_text, lock_changed
    )
    _write_text(out_dir / "graph.json", _graph_json(graph))
    np.save(out_dir / "sea_labels.npy", sea.labels)
    np.save(out_dir / "sea_kinds.npy", sea.kinds)
    _write_text(out_dir / "sea_raster.json", _sea_raster_json(sea))
    _write_text(out_dir / "graph_report.md",
                _build_graph_report(prep, sea, graph))
    if preview:
        img = render_preview(
            sea, land_labels, graph,
            {k: prep.nodes[k].parts for k in prep.nodes},
            prep.cfg,
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        img.save(out_dir / "graph_preview.png")
    return 0


# ------------------------------------------------------------- MP-3: build

_MANIFEST_FILE = "manifest.json"
_GEOMETRY_FILE = "geometry.json"
_CROP_RE = re.compile(r"^([A-Za-z0-9_-]+)=(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)$")


def _png_bytes(img) -> bytes:
    """Encode a PIL image to PNG bytes without touching the filesystem."""
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _check_viewbox(svg_path: Path, cfg: PipelineConfig) -> None:
    """The source root viewBox must equal ``view.width x view.height``."""
    root = None
    context = etree.iterparse(str(svg_path), events=("start",))
    for _event, el in context:
        root = el
        break
    del context
    if root is None or root.get("viewBox") is None:
        raise PipelineError(
            DATA_INVALID, f"{svg_path}: root <svg> has no viewBox"
        )
    try:
        vals = [float(v) for v in root.get("viewBox").split()]
    except ValueError:
        raise PipelineError(
            DATA_INVALID,
            f"{svg_path}: unparsable viewBox {root.get('viewBox')!r}",
        )
    want = [0.0, 0.0, float(cfg.view.width), float(cfg.view.height)]
    if vals != want:
        raise PipelineError(
            VIEWBOX_MISMATCH,
            f"source viewBox {vals} does not match view config {want}",
        )


def _parse_crops(specs: list[str] | None) -> list[tuple[str, tuple]]:
    crops = []
    for spec in specs or []:
        m = _CROP_RE.match(spec)
        if not m:
            raise PipelineError(
                DATA_INVALID,
                f"bad --crop spec {spec!r}; expected NAME=x0,y0,x1,y1",
            )
        name = m.group(1)
        x0, y0, x1, y1 = (float(v) for v in m.groups()[1:])
        if not (x0 < x1 and y0 < y1):
            raise PipelineError(
                DATA_INVALID, f"--crop {spec!r}: empty rectangle"
            )
        crops.append((name, (x0, y0, x1, y1)))
    return crops


def _build_report(
    prep: _Prep,
    sea: SeaRaster,
    graph,
    land_geoms: dict,
    sea_build,
    outside_build,
    metrics: dict,
    land_dev: dict,
    repairs: list,
    paths: dict,
    outside_d: str,
    geom_bytes: int,
    manifest_bytes: int,
    geometry_version: str,
    inputs: dict,
    playable: list,
) -> str:
    """Deterministic ``build_report.md`` — no timestamps."""
    clip = box(*playable)
    clip_boundary = clip.boundary
    fragments = sorted(
        (
            p
            for p in _polygon_list(outside_build.outside)
            if p.area < 5.0
            and clip.covers(p)
            and p.disjoint(clip_boundary)
        ),
        key=lambda p: (-p.area, p.bounds),
    )
    cfg = prep.cfg
    by_id = {n.id: n for n in graph.nodes}
    land_keys = {n.key for n in graph.nodes if n.kind != KIND_SEA}

    land_v = sum(_vertex_count(land_geoms[k]) for k in land_geoms)
    sea_v = sum(_vertex_count(g) for g in sea_build.geoms.values())
    out_v = _vertex_count(outside_build.outside)
    land_b = sum(
        len(paths[str(n.id)].encode("utf-8"))
        for n in graph.nodes
        if n.kind != KIND_SEA
    )
    sea_b = sum(
        len(paths[str(n.id)].encode("utf-8"))
        for n in graph.nodes
        if n.kind == KIND_SEA
    )
    out_b = len(outside_d.encode("utf-8"))
    degree = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        degree[e.a] += 1
        degree[e.b] += 1
    max_deg = max(degree.values())
    max_key = by_id[max(degree, key=lambda i: (degree[i], i))].key

    devs = sorted(land_dev.values())
    max_dev = max(devs)
    mean_dev = sum(devs) / len(devs)
    worst_key = max(land_dev, key=lambda k: (land_dev[k], k))

    small = [
        (n.key, metrics[n.key].area)
        for n in graph.nodes
        if metrics[n.key].area < cfg.report.small_area_warn
    ]

    lines = [
        "# map_pipeline — build report",
        "",
        f"- Nodes: {len(graph.nodes)} ({len(land_keys)} land, "
        f"{len(graph.nodes) - len(land_keys)} sea)",
        f"- Edges: {len(graph.edges)}",
        "",
        "## Geometry",
        "",
        f"- Land paths: {land_v} vertices, {land_b} bytes",
        f"- Sea paths: {sea_v} vertices, {sea_b} bytes",
        f"- Outside: {out_v} vertices, {out_b} bytes",
        f"- geometry.json: {geom_bytes} bytes "
        f"({round(100 * geom_bytes / cfg.limits.max_geometry_bytes, 1)}% "
        f"of the {cfg.limits.max_geometry_bytes} limit)",
        f"- manifest.json: {manifest_bytes} bytes "
        f"({round(100 * manifest_bytes / cfg.limits.max_manifest_bytes, 1)}% "
        f"of the {cfg.limits.max_manifest_bytes} limit)",
        f"- geometry_version: {geometry_version}",
        "",
        "## Simplification",
        "",
        f"- Land Hausdorff deviation: max {round(max_dev, 4)} "
        f"(`{worst_key}`), mean {round(mean_dev, 4)}",
        "- Land needle-cleanup repairs: "
        + (", ".join(f"`{k}`" for k in repairs) if repairs else "none"),
        f"- Sea faces: {sea_build.face_count} "
        f"(labelled {sea_build.labelled_faces}), vertices before the cut "
        f"{sea_build.vertices_before_cut}, after the cut "
        f"{sea_build.vertices_after_cut}",
        f"- Sea area: {round(sea_build.area_before_cut, 2)} before the "
        f"land cut, {round(sea_build.area_after_cut, 2)} after",
        f"- Fjord fill: merged {sea_build.fill_merged} leftover pieces "
        f"({round(sea_build.fill_merged_area, 2)} sq. units) into sea "
        f"zones; {sea_build.fill_leftover} pieces <= "
        f"{cfg.sea_cut.fill_max_area} sq. units touch no zone "
        f"({round(sea_build.fill_leftover_area, 2)} sq. units)",
        f"- Lake region: {outside_build.lake_pieces} pieces, area "
        f"{round(outside_build.lake_area, 2)}, raster spill "
        f"{round(outside_build.lake_spill, 3)}",
        f"- Lakes away from playable land (no window): "
        f"{outside_build.lakes_dropped} pieces, "
        f"{round(outside_build.lakes_dropped_area, 2)} sq. units",
        f"- Lake windows in outside: {outside_build.lake_windows} "
        f"(enclosed holes {outside_build.lake_holes})",
        f"- Lake pocket rims absorbed into windows: "
        f"{outside_build.lake_rims} pieces, "
        f"{round(outside_build.lake_rims_area, 2)} sq. units",
        f"- Outside holes dropped: {outside_build.holes_dropped}",
        f"- Small isolated outside fragments inside playable area "
        f"(<5 sq. units): {len(fragments)}",
        *(
            f"  - area {round(p.area, 2)}, centroid "
            f"({round(p.centroid.x, 2)}, {round(p.centroid.y, 2)})"
            for p in fragments[:10]
        ),
        "",
        "## Limits",
        "",
        f"- Max node degree: {max_deg} (`{max_key}`), limit "
        f"{cfg.limits.max_edges_per_node}",
        f"- Node count: {len(graph.nodes)}, limit {cfg.limits.max_nodes}",
        "",
        "## Small nodes",
        "",
    ]
    if not small:
        lines.append("- none")
    for key, area in small:
        lines.append(f"- `{key}`: area {area} < {cfg.report.small_area_warn}")
    lines += ["", "## Input hashes (inputs_sha256)", ""]
    for name in ("source", "boundary", "overrides", "ids_lock"):
        lines.append(f"- {name}: `{inputs[name]}`")
    lines.append("")
    return "\n".join(lines)


def run_build(
    data_dir: Path,
    out_dir: Path,
    check: bool = False,
    preview: bool = True,
    crops: list[str] | None = None,
) -> int:
    """Run steps 1–10. Returns the process exit code (0 ok / 1 failure).

    ``--check`` writes nothing and exits 1 when any of the three final files
    (``manifest.json``, ``geometry.json``, ``ids.lock.json``) would change.
    """
    crop_list = _parse_crops(crops)
    prep = _prepare(data_dir)
    cfg = prep.cfg
    _check_viewbox(data_dir / _SOURCE_FILE, cfg)

    sea = build_seas(prep.nodes, prep.geoms, prep.overrides, cfg)
    ids, new_ids, lock_text, lock_changed = assign_ids(
        data_dir, sorted(prep.nodes), _sea_keys(prep.overrides),
        _lock_keep_extra(prep.boundary),
        renames=_renames_map(prep.overrides),
    )
    ordered = sorted(prep.nodes, key=lambda k: ids[k])
    land_labels = land_label_raster(
        [prep.nodes[k] for k in ordered], sea.land, sea.frame
    )
    graph = build_graph(
        prep.nodes, sea, ids, prep.overrides, cfg, land_labels
    )

    land_geoms, land_dev, land_repairs = build_land_geometries(
        prep.nodes, cfg
    )
    land_mask = build_land_mask(land_geoms, prep, sea, cfg)
    playable = playable_bbox(land_geoms, prep.overrides, cfg)
    zone_ids = {k: ids[k] for k in sea.zone_keys}
    sea_build = build_sea_geometries(
        sea, land_mask, cfg, box(*playable), zone_ids,
    )
    all_geoms = {k: land_geoms[k] for k in sorted(land_geoms)}
    for key in sorted(sea_build.geoms):
        all_geoms[key] = sea_build.geoms[key]

    # Canonical geometry = what geometry.json will contain. Union
    # intersection vertices are not on the grid, so the in-memory polygons
    # differ from the written file by rounding; metrics, the nodes union
    # and ``outside`` must be derived from the serialised form or a test
    # that recomputes ``buffer(N, -0.2)`` from geometry.json would see a
    # different (order- and rounding-sensitive) boundary.
    paths = {
        str(ids[key]): dumps(all_geoms[key]) for key in sorted(all_geoms)
    }
    canon = {
        key: (
            (lambda p: p[0] if len(p) == 1 else MultiPolygon(p))(
                parse_path(paths[str(ids[key])])
            )
        )
        for key in all_geoms
    }
    metrics = {
        k: node_metrics(canon[k], cfg) for k in sorted(canon)
    }

    view_poly = box(0.0, 0.0, float(cfg.view.width), float(cfg.view.height))
    land_keys = sorted(
        (k for k in canon if k in land_geoms), key=lambda k: ids[k]
    )
    land_union = safe_union(
        [p for k in land_keys for p in _polygon_list(canon[k])]
    )
    # 1.10: a water body that touches no node stays dark — windows are cut
    # only for bays/lakes within contact distance of the node union.
    nodes_union = safe_union(
        [p for k in canon for p in _polygon_list(canon[k])]
    )
    (
        lake_region, lake_pieces, lake_area, lake_spill,
        lakes_dropped, lakes_dropped_area,
    ) = build_lake_region(
        sea, land_mask, view_poly, cfg, land_union, nodes_union,
    )
    bay_region = build_bay_region(
        sea, land_mask, view_poly, cfg, nodes_union
    )
    outside_build = build_outside(
        [canon[k] for k in sorted(canon, key=lambda k: ids[k])],
        lake_region, view_poly, cfg, bay_region,
    )
    outside_build.lake_pieces = lake_pieces
    outside_build.lake_area = lake_area
    outside_build.lake_spill = lake_spill
    outside_build.lakes_dropped = lakes_dropped
    outside_build.lakes_dropped_area = lakes_dropped_area

    outside_d = dumps(outside_build.outside)
    sea_water_d = dumps(bay_region) if bay_region is not None else ""
    geom_doc, geom_text = build_geometry_doc(paths, outside_d, sea_water_d)
    geom_bytes = len(geom_text.encode("utf-8"))
    if geom_bytes > cfg.limits.max_geometry_bytes:
        land_b = sum(
            len(paths[str(n.id)]) for n in graph.nodes if n.kind != KIND_SEA
        )
        sea_b = sum(
            len(paths[str(n.id)]) for n in graph.nodes if n.kind == KIND_SEA
        )
        raise PipelineError(
            GEOMETRY_TOO_LARGE,
            f"geometry.json would be {geom_bytes} bytes, over "
            f"limits.max_geometry_bytes {cfg.limits.max_geometry_bytes}",
            [
                f"land paths: {land_b} bytes",
                f"sea paths: {sea_b} bytes",
                f"outside: {len(outside_d)} bytes",
                "suggestion: raise simplify.tolerance (e.g. "
                f"{round(cfg.simplify.tolerance * 2, 3)}) and/or "
                "simplify.sea_tolerance "
                f"(e.g. {round(cfg.simplify.sea_tolerance * 1.5, 3)})",
            ],
        )

    inputs = build_inputs_sha256(
        data_dir / _SOURCE_FILE,
        data_dir / _BOUNDARY_FILE,
        data_dir / _OVERRIDES_FILE,
        lock_text,
    )
    manifest = build_manifest(
        graph,
        prep.nodes,
        prep.overrides,
        metrics,
        inputs,
        geom_doc["version"],
        [0, 0, cfg.view.width, cfg.view.height],
        playable,
        cfg,
    )
    manifest_text = dumps_manifest(manifest)
    manifest_bytes = len(manifest_text.encode("utf-8"))
    validate_manifest(manifest, set(paths), manifest_bytes, cfg)

    report_text = _build_report(
        prep, sea, graph, land_geoms, sea_build, outside_build, metrics,
        land_dev, land_repairs, paths, outside_d, geom_bytes,
        manifest_bytes, geom_doc["version"], inputs, playable,
    )

    if check:
        changed = lock_changed
        for name, text in (
            (_MANIFEST_FILE, manifest_text),
            (_GEOMETRY_FILE, geom_text),
        ):
            target = data_dir / name
            if (
                not target.exists()
                or _read_text_normalized(target) != text
            ):
                changed = True
        return 1 if changed else 0

    # Render the preview images fully in memory first: if anything below
    # fails, no final file in --data-dir has been touched yet.
    preview_pngs: list[tuple[Path, bytes]] = []
    if preview:
        parsed = {k: parse_path(d) for k, d in paths.items()}
        outside_parts = parse_path(outside_d)
        sea_water_parts = parse_path(sea_water_d) if sea_water_d else []
        sea_ids = {
            str(n.id) for n in graph.nodes if n.kind == KIND_SEA
        }
        prev_dir = data_dir / "preview"
        img = render_map_preview(
            parsed, outside_parts, tuple(playable),
            cfg.preview.pixels_per_unit, cfg.preview.colors, sea_ids,
            sea_water_parts,
        )
        preview_pngs.append((prev_dir / "map_preview.png", _png_bytes(img)))
        for name, rect in crop_list:
            img = render_map_preview(
                parsed, outside_parts, rect,
                cfg.preview.crop_pixels_per_unit, cfg.preview.colors,
                sea_ids, sea_water_parts,
            )
            preview_pngs.append(
                (prev_dir / f"map_crop_{name}.png", _png_bytes(img))
            )

    _write_nodes_outputs(
        data_dir, out_dir, prep, ids, new_ids, lock_text, lock_changed
    )
    _write_text(data_dir / _MANIFEST_FILE, manifest_text)
    _write_text(data_dir / _GEOMETRY_FILE, geom_text)
    _write_text(out_dir / "graph.json", _graph_json(graph))
    np.save(out_dir / "sea_labels.npy", sea.labels)
    np.save(out_dir / "sea_kinds.npy", sea.kinds)
    _write_text(out_dir / "sea_raster.json", _sea_raster_json(sea))
    _write_text(out_dir / "graph_report.md",
                _build_graph_report(prep, sea, graph))
    _write_text(out_dir / "build_report.md", report_text)
    for path, payload in preview_pngs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return 0
