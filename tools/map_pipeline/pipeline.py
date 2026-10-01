"""Steps 3–4 of the pipeline contract (Spec, Appendix A): select the game
field, drop/keep listed parts, detect isolated parts and assign stable ids.

Deterministic by construction: sorted iteration everywhere, no timestamps, no
randomness — identical inputs produce byte-identical outputs.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from shapely import STRtree
from shapely.geometry import Point, Polygon

from .errors import (
    BOUNDARY_UNKNOWN_ID,
    DATA_INVALID,
    DROP_PART_EMPTIES_PROVINCE,
    DROP_PART_NOT_FOUND,
    ISOLATED_PART,
    KEY_COLLISION,
    KEY_INVALID,
    KEY_REMOVED,
    PipelineError,
    PipelineFailure,
)
from .models import (
    IdsLock,
    MIN_NODE_ID,
    Boundary,
    Overrides,
    collect_reference_errors,
    load_boundary,
    load_ids_lock,
    load_overrides,
)
from .pipeline_config_schema import PipelineConfig, load_pipeline_config
from .svg_source import build_geometries, read_province_paths

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


def _canonical_lock(ids: dict[str, int]) -> str:
    ordered = {k: v for k, v in sorted(ids.items(), key=lambda kv: kv[1])}
    doc = {"version": 1, "ids": ordered}
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _assign_ids(
    data_dir: Path, keys: list[str]
) -> tuple[dict[str, int], list[int], str, bool]:
    """Load the lock, append new keys.

    Returns ``(ids, new_ids, canonical_text, changed)``: ``ids`` maps every
    included key, ``new_ids`` lists freshly assigned ids in ascending order,
    ``changed`` says the canonical text differs from the file on disk.
    """
    lock_path = data_dir / _IDS_LOCK_FILE
    existing: dict[str, int] = {}
    old_text: str | None = None
    if lock_path.exists():
        lock: IdsLock = load_ids_lock(lock_path)
        existing = dict(lock.ids)
        old_text = lock_path.read_text(encoding="utf-8")

    key_set = set(keys)
    removed = sorted(k for k in existing if k not in key_set)
    if removed:
        raise PipelineFailure(
            [
                PipelineError(
                    KEY_REMOVED,
                    f"ids.lock.json key {k!r} is no longer an included "
                    "province; remove it manually if intentional",
                )
                for k in removed
            ]
        )

    ids = {k: existing[k] for k in keys if k in existing}
    new_ids: list[int] = []
    next_id = max(existing.values(), default=MIN_NODE_ID - 1) + 1
    for key in keys:
        if key not in ids:
            ids[key] = next_id
            new_ids.append(next_id)
            next_id += 1

    text = _canonical_lock(ids)
    return ids, new_ids, text, text != old_text


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_report(
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


def run_nodes(data_dir: Path, out_dir: Path, check: bool = False) -> int:
    """Run steps 1–4. Returns the process exit code (0 ok / 1 failure)."""
    cfg = load_pipeline_config()
    boundary = load_boundary(data_dir / _BOUNDARY_FILE)
    overrides = load_overrides(data_dir / _OVERRIDES_FILE)
    ref_errors = collect_reference_errors(overrides, boundary)
    if ref_errors:
        raise PipelineFailure(ref_errors)

    paths = read_province_paths(data_dir / _SOURCE_FILE)
    nodes, info = _select_nodes(paths, boundary, overrides)
    geoms = build_geometries(paths, cfg.clean)
    for node in nodes.values():
        node.parts = geoms[node.source_name]

    applied = _apply_drop_parts(nodes, overrides)
    _check_isolated_parts(nodes, geoms, boundary, overrides, cfg)

    keys = sorted(nodes)
    ids, new_ids, lock_text, lock_changed = _assign_ids(data_dir, keys)

    if check:
        return 1 if lock_changed else 0

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
        for node in nodes.values()
    ]
    records.sort(key=lambda r: r["id"])
    _write_text(
        out_dir / "land_nodes.json",
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
    )

    new_id_range = (new_ids[0], new_ids[-1]) if new_ids else None
    _write_text(
        out_dir / "report.md",
        _build_report(
            len(paths), boundary, nodes, applied, info, new_id_range
        ),
    )
    return 0
