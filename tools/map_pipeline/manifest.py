"""Appendix A step 10: the ``manifest.json`` document and input hashes.

Key order inside the file follows the Spec Part 1 layout exactly (insertion
order, ``indent=1``, UTF-8, one trailing newline); INV-M10 pins
``inputs_sha256`` to the raw bytes of the four input files.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .geometry import NodeMetrics
from .graph import KIND_LAND, Graph
from .models import Overrides
from .pipeline_config_schema import PipelineConfig


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha256(path: Path) -> str:
    """SHA-256 of a text input with CRLF normalised to LF.

    The repository uses ``core.autocrlf`` on Windows, so YAML/JSON inputs
    may carry CRLF in a worktree while the committed blob is LF. Hashing
    the normalised text keeps ``inputs_sha256`` identical across platforms.
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def build_inputs_sha256(
    source_path: Path,
    boundary_path: Path,
    overrides_path: Path,
    lock_text: str,
) -> dict:
    """INV-M10 hashes: raw SVG bytes + normalised text of the rest.

    ``source/map.svg`` is marked ``-text`` and hashed as raw bytes; the
    YAML inputs and the final ``ids.lock.json`` are hashed after
    CRLF -> LF normalisation (the canonical lock text already uses LF).
    """
    return {
        "source": file_sha256(source_path),
        "boundary": text_sha256(boundary_path),
        "overrides": text_sha256(overrides_path),
        "ids_lock": hashlib.sha256(lock_text.encode("utf-8")).hexdigest(),
    }


def playable_bbox(
    land_geoms: dict, overrides: Overrides, cfg: PipelineConfig
) -> list[float]:
    """Included-land bbox + sea_margin, clipped to the view, grid outward."""
    xs0, ys0, xs1, ys1 = [], [], [], []
    for geom in land_geoms.values():
        minx, miny, maxx, maxy = geom.bounds
        xs0.append(minx)
        ys0.append(miny)
        xs1.append(maxx)
        ys1.append(maxy)
    m = overrides.sea_margin
    w, h = float(cfg.view.width), float(cfg.view.height)
    grid = cfg.output.grid
    return [
        round(math.floor(max(0.0, min(xs0) - m) / grid + 1e-9) * grid, 2),
        round(math.floor(max(0.0, min(ys0) - m) / grid + 1e-9) * grid, 2),
        round(math.ceil(min(w, max(xs1) + m) / grid - 1e-9) * grid, 2),
        round(math.ceil(min(h, max(ys1) + m) / grid - 1e-9) * grid, 2),
    ]


def build_manifest(
    graph: Graph,
    land: dict,  # key -> pipeline _Node
    overrides: Overrides,
    metrics: dict[str, NodeMetrics],
    inputs: dict,
    geometry_version: str,
    view_box: list[float],
    playable: list[float],
    cfg: PipelineConfig,
) -> dict:
    """Assemble the manifest document (insertion order = Spec Part 1)."""
    nodes = []
    for gn in graph.nodes:
        mt = metrics[gn.key]
        if gn.kind == KIND_LAND:
            node = land[gn.key]
            nodes.append(
                {
                    "id": gn.id,
                    "key": gn.key,
                    "kind": "LAND",
                    "name": node.source_name.replace("_", " "),
                    "name_ru": overrides.names_ru.get(gn.key) or None,
                    "source_name": node.source_name,
                    "anchor": [mt.anchor[0], mt.anchor[1]],
                    "bbox": list(mt.bbox),
                    "area": mt.area,
                }
            )
        else:
            nodes.append(
                {
                    "id": gn.id,
                    "key": gn.key,
                    "kind": "SEA",
                    "name": gn.name_ru,
                    "name_ru": gn.name_ru,
                    "source_name": None,
                    "anchor": [mt.anchor[0], mt.anchor[1]],
                    "bbox": list(mt.bbox),
                    "area": mt.area,
                }
            )
    edges = []
    for e in graph.edges:
        if e.type == "strait":
            edges.append(
                {
                    "a": e.a,
                    "b": e.b,
                    "type": "strait",
                    "name": e.name,
                    "multiplier": e.multiplier,
                }
            )
        else:
            edges.append(
                {
                    "a": e.a,
                    "b": e.b,
                    "type": e.type,
                    "len": None if e.len is None else round(e.len, 3),
                }
            )
    return {
        "schema_version": 1,
        "geometry_version": geometry_version,
        "view_box": view_box,
        "playable_bbox": playable,
        "georef": {
            "projection": "gall_stereographic",
            "x0": cfg.georef.x0,
            "k": cfg.georef.k,
            "y0": cfg.georef.y0,
            "m": cfg.georef.m,
        },
        "inputs_sha256": inputs,
        "nodes": nodes,
        "edges": edges,
    }


def dumps_manifest(doc: dict) -> str:
    """Pretty JSON: ``indent=1``, UTF-8, insertion order, trailing newline."""
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
