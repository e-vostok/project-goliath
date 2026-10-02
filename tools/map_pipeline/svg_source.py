"""Steps 1–2 of the pipeline contract (Spec, Appendix A): read the source SVG
and convert each province path into a list of polygon parts.

The tool never modifies ``data/map/source/``. Pattern paths inside ``<defs>``
are ignored entirely; a ``transform`` attribute on a province path or any of
its ancestors is a hard error (``UNSUPPORTED_TRANSFORM``) because coordinates
are expected to already be in the base ``0 0 1200 680`` space.
"""
from __future__ import annotations

from itertools import chain
from pathlib import Path

from lxml import etree
from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union
from svgpathtools import Line, parse_path

from .errors import (
    DATA_INVALID,
    DUPLICATE_ID,
    UNSUPPORTED_TRANSFORM,
    PipelineError,
    PipelineFailure,
)
from .pipeline_config_schema import CleanConfig


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_province_paths(svg_path: Path) -> dict[str, str]:
    """Return ``{source_name: path_d}`` for every province path.

    Province paths are all ``<path>`` elements not inside ``<defs>``.
    Independent defects are collected and reported together.
    """
    try:
        tree = etree.parse(str(svg_path))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(
            DATA_INVALID, f"cannot parse SVG source {svg_path}: {exc}"
        )

    errors: list[PipelineError] = []
    paths: dict[str, str] = {}
    for el in tree.getroot().iter():
        if _local(el.tag) != "path":
            continue
        if any(_local(a.tag) == "defs" for a in el.iterancestors()):
            continue
        if any(
            node.get("transform") is not None
            for node in chain([el], el.iterancestors())
        ):
            errors.append(
                PipelineError(
                    UNSUPPORTED_TRANSFORM,
                    f"path {el.get('id')!r} or an ancestor carries a "
                    "transform attribute",
                )
            )
            continue
        pid = el.get("id")
        d = el.get("d")
        if not pid:
            errors.append(
                PipelineError(DATA_INVALID, "province path without an id")
            )
            continue
        if pid in paths:
            errors.append(
                PipelineError(DUPLICATE_ID, f"duplicate province id {pid!r}")
            )
            continue
        if not d:
            errors.append(
                PipelineError(
                    DATA_INVALID, f"province path {pid!r} has no 'd' attribute"
                )
            )
            continue
        paths[pid] = d
    if errors:
        raise PipelineFailure(errors)
    return paths


def safe_union(geoms: list):
    """``unary_union`` with a pairwise fallback for a GEOS noding quirk.

    ``unary_union`` can raise ``TopologyException: side location conflict``
    on some disjoint inputs (GEOS 3.13); a pairwise union handles them.
    """
    geoms = list(geoms)
    try:
        return unary_union(geoms)
    except GEOSException:
        out = GeometryCollection()
        for g in geoms:
            out = out.union(g)
        return out


def _polygon_parts(geom, min_area: float) -> list[Polygon]:
    """Extract every polygonal part of ``geom`` of at least ``min_area``."""
    out: list[Polygon] = []
    stack = [geom]
    while stack:
        g = stack.pop()
        if isinstance(g, Polygon):
            if not g.is_empty and g.area >= min_area:
                out.append(g)
        elif isinstance(g, (MultiPolygon, GeometryCollection)):
            stack.extend(g.geoms)
    return out


def path_to_polygon_parts(d: str, cfg: CleanConfig) -> list[Polygon]:
    """Convert one SVG path string into a sorted list of polygon parts.

    Line segments contribute their start point only; every other segment is
    sampled at ``sample_points_per_curve`` equally spaced fractions ``i/n``
    (the end point of the last segment is appended once). Rings shorter than
    four points are skipped. Invalid rings go through ``shapely.make_valid``;
    subpaths are merged by ``unary_union`` (holes are not preserved, matching
    the validated analysis).
    """
    try:
        path = parse_path(d)
    except Exception as exc:
        raise PipelineError(
            DATA_INVALID, f"cannot parse path data {d[:40]!r}…: {exc}"
        )

    polygons: list[Polygon] = []
    for sub in path.continuous_subpaths():
        ring: list[tuple[float, float]] = []
        for seg in sub:
            if isinstance(seg, Line):
                ring.append((seg.start.real, seg.start.imag))
            else:
                n = cfg.sample_points_per_curve
                for i in range(n):
                    p = seg.point(i / n)
                    ring.append((p.real, p.imag))
        if len(sub):
            end = sub[-1].end
            ring.append((end.real, end.imag))
        if len(ring) < 4:
            continue
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = make_valid(poly)
        polygons.extend(_polygon_parts(poly, cfg.min_part_area))

    merged = safe_union(polygons) if polygons else GeometryCollection()
    parts = _polygon_parts(merged, cfg.min_part_area)
    parts.sort(key=lambda p: tuple(p.bounds))
    return parts


def build_geometries(
    paths: dict[str, str], cfg: CleanConfig
) -> dict[str, list[Polygon]]:
    """Convert every source path to polygon parts; report parse failures."""
    errors: list[PipelineError] = []
    geoms: dict[str, list[Polygon]] = {}
    for name in sorted(paths):
        try:
            geoms[name] = path_to_polygon_parts(paths[name], cfg)
        except PipelineError as exc:
            exc.message = f"{name}: {exc.message}"
            errors.append(exc)
    if errors:
        raise PipelineFailure(errors)
    return geoms
