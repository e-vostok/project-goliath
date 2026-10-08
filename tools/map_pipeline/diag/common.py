"""Shared loaders/geometry helpers for the map2_9 diagnosis scripts."""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

from tools.map_pipeline.svgpath import parse_path

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "map"
REF = REPO / "tools" / "map_pipeline" / "reference"


def load_manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def load_geometry() -> dict:
    return json.loads((DATA / "geometry.json").read_text(encoding="utf-8"))


def nodes_by_id(manifest: dict) -> dict[int, dict]:
    return {n["id"]: n for n in manifest["nodes"]}


def nodes_by_key(manifest: dict) -> dict[str, dict]:
    return {n["key"]: n for n in manifest["nodes"]}


def edge_index(manifest: dict) -> dict[tuple[int, int], dict]:
    return {(e["a"], e["b"]): e for e in manifest["edges"]}


def node_parts(geometry: dict, node_id: int) -> list[Polygon]:
    """Polygon parts of a node's path (holes kept inside each part)."""
    return parse_path(geometry["paths"][str(node_id)])


def node_geom(geometry: dict, node_id: int):
    """Union of a node's parts as one shapely geometry."""
    parts = node_parts(geometry, node_id)
    if len(parts) == 1:
        return parts[0]
    return MultiPolygon(parts)


def fmt_edge(e: dict | None) -> str:
    if e is None:
        return "none"
    extra = []
    if e.get("name"):
        extra.append(f"name={e['name']!r}")
    if e.get("multiplier") is not None:
        extra.append(f"multiplier={e['multiplier']}")
    if e.get("len") is not None:
        extra.append(f"len={e['len']}")
    return e["type"] + (" (" + ", ".join(extra) + ")" if extra else "")


def sea_name(node: dict | None) -> str:
    if node is None:
        return "-"
    return node.get("name_ru") or node.get("name") or node["key"]
