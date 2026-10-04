"""Shared helpers for the relief prototype (map_polish_5, stage 1).

Prototype only -- nothing here is product code. Everything reads the
current data/map artifacts read-only and writes into
``tools/map_pipeline/relief_proto/`` and
``tools/map_pipeline/reference/relief_*``.

Georeference: Spec 3.7 -- the source map is Gall stereographic,
``x = x0 + k*lon_deg``, ``y = y0 - m*tan(lat_rad/2)`` with the constants
from ``manifest.georef``. ``lonlat_to_base``/``base_to_lonlat`` implement
it and its inverse.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from tools.map_pipeline.svgpath import parse_path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "map"
PROTO_DIR = Path(__file__).resolve().parent
DL_DIR = PROTO_DIR / "dl"
OUT_DIR = PROTO_DIR / "out"
REF_DIR = PROTO_DIR.parent / "reference"


def load_geometry() -> dict:
    return json.loads((DATA_DIR / "geometry.json").read_text("utf-8"))


def load_manifest() -> dict:
    return json.loads((DATA_DIR / "manifest.json").read_text("utf-8"))


def load_map_config() -> dict:
    return yaml.safe_load(
        (REPO_ROOT / "configs" / "01_map.yaml").read_text("utf-8")
    )


def load_boundary() -> dict:
    return yaml.safe_load((DATA_DIR / "boundary.yaml").read_text("utf-8"))


# ------------------------------------------------------------------ georef


def lonlat_to_base(lon_deg, lat_deg, georef: dict):
    """Spec 3.7 forward transform (lon deg, lat deg -> base units)."""
    x = georef["x0"] + georef["k"] * np.asarray(lon_deg, dtype=float)
    y = georef["y0"] - georef["m"] * np.tan(
        np.radians(np.asarray(lat_deg, dtype=float)) / 2.0
    )
    return x, y


def base_to_lonlat(x, y, georef: dict):
    """Spec 3.7 inverse transform."""
    lon = (np.asarray(x, dtype=float) - georef["x0"]) / georef["k"]
    lat = np.degrees(
        2.0 * np.arctan((georef["y0"] - np.asarray(y, dtype=float))
                        / georef["m"])
    )
    return lon, lat


def frame_lonlat(view: dict, georef: dict, margin: float = 0.0):
    """Lon/lat bbox of the view frame (+margin) via the spec georef."""
    x0 = view["x"] - margin
    x1 = view["x"] + view["width"] + margin
    y0 = view["y"] - margin
    y1 = view["y"] + view["height"] + margin
    lon_a, lat_top = base_to_lonlat(x0, y0, georef)
    lon_b, lat_bot = base_to_lonlat(x1, y1, georef)
    return (
        float(min(lon_a, lon_b)),
        float(max(lon_a, lon_b)),
        float(min(lat_top, lat_bot)),
        float(max(lat_top, lat_bot)),
    )


# ----------------------------------------------------------------- geometry


def node_kinds(manifest: dict) -> dict[str, str]:
    return {str(n["id"]): n["kind"] for n in manifest["nodes"]}


def land_polys(geometry: dict, manifest: dict) -> list[Polygon]:
    """All rendered land: LAND node paths + the outside fill parts."""
    kinds = node_kinds(manifest)
    polys: list[Polygon] = list(parse_path(geometry["outside"]))
    for key, d in geometry["paths"].items():
        if kinds.get(key) != "SEA":
            polys.extend(parse_path(d))
    return polys


def land_union(geometry: dict, manifest: dict):
    """Unary union of every rendered land polygon (shapely geom)."""
    return unary_union(land_polys(geometry, manifest))


def rasterize(polys, rect: tuple[float, float, float, float],
              ppu: float, value: int = 255) -> np.ndarray:
    """Rasterise polygons over ``rect = (x0, y0, x1, y1)`` base units."""
    x0, y0, x1, y1 = rect
    w = max(1, int(round((x1 - x0) * ppu)))
    h = max(1, int(round((y1 - y0) * ppu)))
    img = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(img)

    def to_px(coords):
        return [((x - x0) * ppu, (y - y0) * ppu) for x, y in coords]

    if isinstance(polys, (Polygon, MultiPolygon)):
        polys = [polys]
    for poly in polys:
        if poly.is_empty:
            continue
        geoms = (
            poly.geoms if isinstance(poly, MultiPolygon) else [poly]
        )
        for g in geoms:
            draw.polygon(to_px(g.exterior.coords), fill=value)
            for hole in g.interiors:
                draw.polygon(to_px(hole.coords), fill=0)
    return np.asarray(img)


def coast_lines(land_geom) -> list[np.ndarray]:
    """Boundary polylines of the land union as Nx2 base-coord arrays."""
    lines: list[np.ndarray] = []
    geoms = (
        list(land_geom.geoms)
        if isinstance(land_geom, MultiPolygon)
        else [land_geom]
    )
    for g in geoms:
        rings = [g.exterior, *g.interiors]
        for ring in rings:
            pts = np.asarray(ring.coords, dtype=float)
            lines.append(pts)
    return lines


# -------------------------------------------------------------------- misc


def km_per_unit(georef: dict, lat_deg: float = 50.0) -> float:
    """Meridional km per base unit at ``lat_deg`` (Spec 3.7 formula)."""
    phi = math.radians(lat_deg)
    units_per_rad = georef["m"] / (2.0 * math.cos(phi / 2.0) ** 2)
    deg_per_unit = math.degrees(1.0 / units_per_rad)
    return 111.195 * deg_per_unit
