"""Canonical ``d`` attribute format for ``geometry.json`` (MP-3).

Path strings use only absolute ``M``/``Z`` commands: each polygon ring is
``M x y x y ... Z`` (implicit lineto, the closing vertex is NOT repeated).
A node's string concatenates all of its parts without separators; inside a
part the exterior ring comes first, then each hole as its own ``M ... Z``.
Rings are oriented with ``shapely.geometry.polygon.orient(poly, sign=1.0)``:
exteriors counter-clockwise, holes clockwise in the SVG y-down plane.

Coordinates lie on the ``output.grid`` grid and are written with at most two
decimals: no trailing zeros, no ``-0``, no scientific notation, single
spaces. ``parse_path`` reads the format back; ring orientation tells
exteriors from holes (positive signed area starts a new part).
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .svg_source import _polygon_parts

_CHUNK_RE = re.compile(r"M\s*((?:-?\d+(?:\.\d+)?\s+)*-?\d+(?:\.\d+)?)\s*Z")


def format_number(v: float) -> str:
    """Grid-snapped coordinate as text: 2 decimals max, no ``-0``."""
    s = f"{Decimal(round(v * 100)) / 100:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def polygons_of(geom) -> list[Polygon]:
    """Polygon parts of a (Multi)Polygon, sorted by descending area."""
    parts = _polygon_parts(geom, 0.0)
    parts.sort(key=lambda p: (-p.area, p.bounds))
    return parts


def _ring_d(coords) -> str:
    pts = [(x, y) for x, y in coords[:-1]]  # drop the repeated closer
    return "M " + " ".join(
        f"{format_number(x)} {format_number(y)}" for x, y in pts
    ) + " Z"


def dumps(geom) -> str:
    """Serialise a (Multi)Polygon into the canonical path string."""
    chunks: list[str] = []
    for part in polygons_of(geom):
        part = orient(part, sign=1.0)
        chunks.append(_ring_d(part.exterior.coords))
        chunks.extend(_ring_d(r.coords) for r in part.interiors)
    return "".join(chunks)


def _signed_area(coords: list[tuple[float, float]]) -> float:
    s = 0.0
    n = len(coords)
    for i in range(n):
        x0, y0 = coords[i]
        x1, y1 = coords[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2


def parse_path(d: str) -> list[Polygon]:
    """Parse a canonical path string back into polygon parts.

    A ring with positive signed area starts a new part; a negative one is a
    hole of the current part. Malformed input raises ``ValueError``.
    """
    rings: list[list[tuple[float, float]]] = []
    pos = 0
    for m in _CHUNK_RE.finditer(d):
        if d[pos:m.start()].strip():
            raise ValueError(f"unparsed fragment {d[pos:m.start()]!r}")
        pos = m.end()
        nums = m.group(1).split()
        if len(nums) < 6 or len(nums) % 2:
            raise ValueError("ring needs at least 3 coordinate pairs")
        it = iter(nums)
        rings.append([(float(x), float(y)) for x, y in zip(it, it)])
    if pos != len(d) or d[pos:].strip():
        raise ValueError(f"unparsed tail {d[pos:]!r}")

    parts: list[tuple[list, list]] = []
    for coords in rings:
        if _signed_area(coords) > 0:
            parts.append((coords, []))
        elif parts:
            parts[-1][1].append(coords)
        else:
            raise ValueError("path starts with a hole ring")
    return [Polygon(ext, holes) for ext, holes in parts]


def canonical_json(doc: dict) -> str:
    """The Spec 3.6 ``canon`` form: sorted keys, tight separators, UTF-8."""
    return json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def geometry_version(g: dict) -> str:
    """``sha256(canon(G))[:12]`` over the file body without ``version``."""
    return hashlib.sha256(canonical_json(g).encode("utf-8")).hexdigest()[:12]


def build_geometry_doc(
    paths: dict[str, str], outside_d: str, sea_water_d: str
) -> tuple[dict, str]:
    """Assemble ``geometry.json`` content; returns ``(doc, text)``."""
    g = {"outside": outside_d, "paths": paths, "sea_water": sea_water_d}
    doc = {"outside": outside_d, "paths": paths,
           "sea_water": sea_water_d,
           "version": geometry_version(g)}
    return doc, canonical_json(doc) + "\n"
