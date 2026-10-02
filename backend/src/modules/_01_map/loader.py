"""
Map data loader: ``data/map/`` -> immutable :class:`MapData`.

Fail-fast (INV-M9): the first violated rule raises :class:`MapDataError`
with a stable machine code and a human message naming the file, the
node/edge and the numbers; nothing is partially loaded. Server startup
will call :func:`load_map_data` in Issue 3.

Check order (the first failure wins):

1. All six input files exist — ``FILE_MISSING``.
2. ``manifest.json`` <= ``limits.max_manifest_bytes`` and
   ``geometry.json`` <= ``limits.max_geometry_bytes``, checked on the
   file size BEFORE reading and parsing — ``LIMIT_EXCEEDED``.
3. JSON parse + strict schema validation of ``manifest.json``,
   ``geometry.json`` and ``ids.lock.json`` — ``SCHEMA_INVALID``.
   ``boundary.yaml``/``overrides.yaml`` are never parsed by the server;
   ``source/map.svg`` is only hashed.
4. ``limits.max_nodes`` / ``limits.max_edges_per_node`` —
   ``LIMIT_EXCEEDED``.
5. INV-M1: manifest <-> ids.lock correspondence, key/id uniqueness,
   ``sea_`` prefix — ``INV_M1``.
6. INV-M2: ``a < b``, unique pairs, existing endpoints, type/kind
   consistency, no loops, multiplier/name/len placement — ``INV_M2``.
7. INV-M3: BFS from the smallest id over all edges reaches every node —
   ``INV_M3``.
8. INV-M6: recomputed geometry hash equals ``manifest.geometry_version``
   and ``geometry.version``; ``paths`` keys equal the node-id set —
   ``INV_M6``.
9. INV-M10: per-file input hashes equal ``manifest.inputs_sha256``
   (rules from ``hashing.INPUT_HASH_RULES``) — ``INV_M10``.

Internal to module ``_01_map``: other modules must use ``service.py``.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

from pydantic import ValidationError

from .config_schema import MapConfig
from .hashing import (
    INPUT_HASH_RULES,
    geometry_version,
    input_sha256,
    normalized_sha256,
)
from .map_data import (
    KIND_SEA,
    MapData,
    MapEdge,
    MapNode,
)
from .map_files import Geometry, IdsLock, Manifest

# Stable machine codes for MapDataError.code.
FILE_MISSING = "FILE_MISSING"
LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
SCHEMA_INVALID = "SCHEMA_INVALID"
INV_M1 = "INV_M1"
INV_M2 = "INV_M2"
INV_M3 = "INV_M3"
INV_M5 = "INV_M5"
INV_M6 = "INV_M6"
INV_M10 = "INV_M10"

_MANIFEST = "manifest.json"
_GEOMETRY = "geometry.json"
_IDS_LOCK = "ids.lock.json"
_BOUNDARY = "boundary.yaml"
_OVERRIDES = "overrides.yaml"
_SOURCE = "source/map.svg"

# All files the directory must contain (checked in this order).
_REQUIRED_FILES = (
    _MANIFEST,
    _GEOMETRY,
    _IDS_LOCK,
    _BOUNDARY,
    _OVERRIDES,
    _SOURCE,
)

# Where each inputs_sha256 key lives, relative to data_dir.
_INPUT_PATHS = {
    "source": Path("source") / "map.svg",
    "boundary": Path(_BOUNDARY),
    "overrides": Path(_OVERRIDES),
    "ids_lock": Path(_IDS_LOCK),
}

_SEA_PREFIX = "sea_"

# INV-M2: the endpoint kinds each edge type may join (sorted pair).
_EDGE_END_KINDS = {
    "land": ("LAND", "LAND"),
    "coast": ("LAND", "SEA"),
    "sea": ("SEA", "SEA"),
    "strait": ("LAND", "LAND"),
}

# Spec 3.11: the legal range of an explicit strait multiplier.
_STRAIT_MULTIPLIER_MIN = 0.05
_STRAIT_MULTIPLIER_MAX = 1.0

_MAX_LISTED = 10


class MapDataError(Exception):
    """A map data violation: stable ``code`` plus a human ``message``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str) -> NoReturn:
    raise MapDataError(code, message)


def _check_files_exist(data_dir: Path) -> None:
    for rel in _REQUIRED_FILES:
        if not (data_dir / rel).is_file():
            _fail(FILE_MISSING, f"{rel}: required map file is missing")


def _check_size(data_dir: Path, rel: str, limit: int) -> None:
    """Enforce a byte limit on the file size BEFORE it is ever read."""
    size = (data_dir / rel).stat().st_size
    if size > limit:
        _fail(
            LIMIT_EXCEEDED,
            f"{rel} is {size} bytes, over the limit {limit} bytes",
        )


def _load_json_model(data_dir: Path, rel: str, model):
    try:
        text = (data_dir / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _fail(SCHEMA_INVALID, f"{rel}: cannot read file: {exc}")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(SCHEMA_INVALID, f"{rel}: invalid JSON: {exc}")
    try:
        return model.model_validate(doc)
    except ValidationError as exc:
        summary = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
            for e in exc.errors()
        )
        _fail(SCHEMA_INVALID, f"{rel} failed schema validation: {summary}")


def _check_limits(manifest: Manifest, config: MapConfig) -> None:
    limits = config.limits
    if len(manifest.nodes) > limits.max_nodes:
        _fail(
            LIMIT_EXCEEDED,
            f"manifest.json has {len(manifest.nodes)} nodes, over "
            f"limits.max_nodes {limits.max_nodes}",
        )
    degree: dict[int, int] = {}
    for e in manifest.edges:
        degree[e.a] = degree.get(e.a, 0) + 1
        degree[e.b] = degree.get(e.b, 0) + 1
    over = sorted(
        i for i, d in degree.items() if d > limits.max_edges_per_node
    )
    if over:
        keys = {n.id: n.key for n in manifest.nodes}
        listed = ", ".join(
            f"{keys.get(i, '?')} (id {i}, degree {degree[i]})"
            for i in over[:_MAX_LISTED]
        )
        _fail(
            LIMIT_EXCEEDED,
            f"node degree over limits.max_edges_per_node "
            f"{limits.max_edges_per_node}: {listed}",
        )


def _check_inv_m1(manifest: Manifest, lock: IdsLock) -> tuple[str, ...]:
    """Manifest <-> ids.lock correspondence; returns warnings."""
    seen_keys: set[str] = set()
    seen_ids: set[int] = set()
    for n in manifest.nodes:
        if n.key in seen_keys:
            _fail(INV_M1, f"manifest.json: duplicate node key {n.key!r}")
        if n.id in seen_ids:
            _fail(INV_M1, f"manifest.json: duplicate node id {n.id}")
        seen_keys.add(n.key)
        seen_ids.add(n.id)

    lock_id_count: dict[int, int] = {}
    for i in lock.ids.values():
        lock_id_count[i] = lock_id_count.get(i, 0) + 1
    for i, count in sorted(lock_id_count.items()):
        if count > 1:
            keys = sorted(k for k, v in lock.ids.items() if v == i)
            _fail(
                INV_M1,
                f"ids.lock.json: id {i} assigned to more than one key: "
                f"{keys}",
            )

    for n in manifest.nodes:
        if n.kind == KIND_SEA and not n.key.startswith(_SEA_PREFIX):
            _fail(
                INV_M1,
                f"manifest.json: SEA node {n.key!r} (id {n.id}) key must "
                f"start with {_SEA_PREFIX!r}",
            )
        if n.kind != KIND_SEA and n.key.startswith(_SEA_PREFIX):
            _fail(
                INV_M1,
                f"manifest.json: LAND node {n.key!r} (id {n.id}) must not "
                f"use the {_SEA_PREFIX!r} prefix",
            )

    for n in manifest.nodes:
        locked = lock.ids.get(n.key)
        if locked is None:
            _fail(
                INV_M1,
                f"manifest.json node {n.key!r} (id {n.id}) is absent "
                f"from ids.lock.json",
            )
        if locked != n.id:
            _fail(
                INV_M1,
                f"manifest.json node {n.key!r} has id {n.id} but "
                f"ids.lock.json records id {locked}",
            )

    # Lock entries with no manifest node are legal (append-only) — listed
    # as warnings, ascending id.
    extra = sorted(
        (i, k) for k, i in lock.ids.items() if k not in seen_keys
    )
    return tuple(
        f"ids.lock.json entry {key!r} (id {i}) has no manifest node"
        for i, key in extra
    )


def _check_inv_m2(manifest: Manifest) -> None:
    by_id = {n.id: n for n in manifest.nodes}
    seen_pairs: set[tuple[int, int]] = set()
    for e in manifest.edges:
        where = f"edge ({e.a}, {e.b}, type {e.type!r})"
        if e.a == e.b:
            _fail(INV_M2, f"manifest.json: {where} is a loop")
        if e.a > e.b:
            _fail(INV_M2, f"manifest.json: {where} has a > b")
        pair = (e.a, e.b)
        if pair in seen_pairs:
            _fail(INV_M2, f"manifest.json: {where} duplicates a pair")
        seen_pairs.add(pair)
        na, nb = by_id.get(e.a), by_id.get(e.b)
        if na is None or nb is None:
            missing = e.a if na is None else e.b
            _fail(
                INV_M2,
                f"manifest.json: {where} endpoint {missing} "
                f"does not exist",
            )
        kinds = tuple(sorted((na.kind, nb.kind)))
        if kinds != _EDGE_END_KINDS[e.type]:
            _fail(
                INV_M2,
                f"manifest.json: {where} joins {na.kind} and {nb.kind}, "
                f"but type {e.type!r} requires "
                f"{'-'.join(_EDGE_END_KINDS[e.type])}",
            )
        if e.type == "strait":
            if not e.name:
                _fail(INV_M2, f"manifest.json: {where} needs a name")
            if e.len is not None:
                _fail(
                    INV_M2,
                    f"manifest.json: {where} must not carry len",
                )
            if e.multiplier is not None and not (
                _STRAIT_MULTIPLIER_MIN
                <= e.multiplier
                <= _STRAIT_MULTIPLIER_MAX
            ):
                _fail(
                    INV_M2,
                    f"manifest.json: {where} multiplier {e.multiplier} "
                    f"outside "
                    f"{_STRAIT_MULTIPLIER_MIN}..{_STRAIT_MULTIPLIER_MAX}",
                )
        else:
            if e.name is not None:
                _fail(
                    INV_M2,
                    f"manifest.json: {where} carries a name, allowed "
                    f"only on strait edges",
                )
            if e.multiplier is not None:
                _fail(
                    INV_M2,
                    f"manifest.json: {where} carries a multiplier, "
                    f"allowed only on strait edges",
                )


def _check_inv_m3(manifest: Manifest) -> None:
    adjacency: dict[int, list[int]] = {
        n.id: [] for n in manifest.nodes
    }
    for e in manifest.edges:
        adjacency[e.a].append(e.b)
        adjacency[e.b].append(e.a)
    if not adjacency:
        return  # an empty node set is vacuously connected
    start = min(adjacency)
    seen = {start}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        for v in adjacency[u]:
            if v not in seen:
                seen.add(v)
                queue.append(v)
    unreachable = sorted(set(adjacency) - seen)
    if unreachable:
        keys = {n.id: n.key for n in manifest.nodes}
        listed = ", ".join(
            f"{keys[i]} (id {i})" for i in unreachable[:_MAX_LISTED]
        )
        suffix = (
            f" and {len(unreachable) - _MAX_LISTED} more"
            if len(unreachable) > _MAX_LISTED
            else ""
        )
        _fail(
            INV_M3,
            f"manifest.json: {len(unreachable)} node(s) unreachable "
            f"from node {start}: {listed}{suffix}",
        )


def _check_inv_m6(manifest: Manifest, geometry: Geometry) -> None:
    computed = geometry_version(geometry.outside, geometry.paths)
    if (
        computed != manifest.geometry_version
        or computed != geometry.version
    ):
        _fail(
            INV_M6,
            f"geometry.json recomputed version {computed} differs from "
            f"geometry.version {geometry.version} or "
            f"manifest.geometry_version {manifest.geometry_version}",
        )
    path_ids = {int(k) for k in geometry.paths}
    node_ids = {n.id for n in manifest.nodes}
    if path_ids != node_ids:
        missing = sorted(node_ids - path_ids)
        extra = sorted(path_ids - node_ids)
        parts = []
        if missing:
            parts.append(
                f"missing paths for nodes {missing[:_MAX_LISTED]}"
            )
        if extra:
            parts.append(f"extra paths for ids {extra[:_MAX_LISTED]}")
        _fail(
            INV_M6,
            "geometry.json paths and manifest nodes differ: "
            + "; ".join(parts),
        )


def _check_inv_m10(data_dir: Path, manifest: Manifest) -> None:
    expected = manifest.inputs_sha256
    for name, rule in INPUT_HASH_RULES.items():
        rel = _INPUT_PATHS[name]
        actual = input_sha256(data_dir / rel, rule)
        recorded = getattr(expected, name)
        if actual != recorded:
            _fail(
                INV_M10,
                f"{rel.as_posix()}: sha256 {actual} differs from "
                f"manifest.inputs_sha256.{name} {recorded} — the inputs "
                f"changed after the manifest was built; re-run the map "
                f"pipeline",
            )


def _build_map_data(
    data_dir: Path,
    manifest: Manifest,
    geometry: Geometry,
    warnings: tuple[str, ...],
) -> MapData:
    nodes = {
        n.id: MapNode(
            id=n.id,
            key=n.key,
            kind=n.kind,
            name=n.name,
            name_ru=n.name_ru,
            source_name=n.source_name,
            anchor=(n.anchor[0], n.anchor[1]),
            bbox=(n.bbox[0], n.bbox[1], n.bbox[2], n.bbox[3]),
            area=n.area,
        )
        for n in sorted(manifest.nodes, key=lambda n: n.id)
    }
    edges = {
        (e.a, e.b): MapEdge(
            a=e.a,
            b=e.b,
            type=e.type,
            name=e.name,
            multiplier=e.multiplier,
            len=e.len,
        )
        for e in manifest.edges
    }
    adjacency: dict[int, list[MapEdge]] = {i: [] for i in nodes}
    for edge in edges.values():
        adjacency[edge.a].append(edge)
        adjacency[edge.b].append(edge)
    adjacency_t = {
        i: tuple(sorted(el, key=lambda e: e.b if e.a == i else e.a))
        for i, el in adjacency.items()
    }
    return MapData(
        nodes=MappingProxyType(nodes),
        nodes_by_key=MappingProxyType(
            {n.key: n for n in nodes.values()}
        ),
        edges=MappingProxyType(edges),
        adjacency=MappingProxyType(adjacency_t),
        geometry_version=manifest.geometry_version,
        manifest_sha256=normalized_sha256(data_dir / _MANIFEST),
        manifest=manifest,
        geometry=geometry,
        warnings=warnings,
    )


def load_map_data(data_dir: Path, config: MapConfig) -> MapData:
    """
    Load and fully validate ``data_dir`` into an immutable ``MapData``.

    Any violation raises :class:`MapDataError` with a stable code; the
    first failure wins and nothing is partially loaded.
    """
    data_dir = Path(data_dir)
    _check_files_exist(data_dir)

    # Size limits are enforced on file size BEFORE any file is read.
    _check_size(data_dir, _MANIFEST, config.limits.max_manifest_bytes)
    _check_size(data_dir, _GEOMETRY, config.limits.max_geometry_bytes)

    manifest = _load_json_model(data_dir, _MANIFEST, Manifest)
    geometry = _load_json_model(data_dir, _GEOMETRY, Geometry)
    lock = _load_json_model(data_dir, _IDS_LOCK, IdsLock)

    _check_limits(manifest, config)
    warnings = _check_inv_m1(manifest, lock)
    _check_inv_m2(manifest)
    _check_inv_m3(manifest)
    _check_inv_m6(manifest, geometry)
    _check_inv_m10(data_dir, manifest)

    return _build_map_data(data_dir, manifest, geometry, warnings)
