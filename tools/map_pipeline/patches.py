"""Appendix A step 3a (Spec 1.9): manual ``geometry_patches``.

Applied to the source geometry after path parsing and cleanup, before the
boundary filter — so a patch may move land from a province that is about to
leave the game to one that stays. ``source/map.svg`` is never touched.

``transfer`` cuts the part of province ``from`` lying inside ``polygon`` and
attaches it to province ``to``. Every violation is ``PATCH_INVALID``:

- ``from``/``to`` must be slugs of existing source provinces, distinct;
- the polygon must be a valid, non-degenerate area;
- the cut part must be exactly one piece and must touch ``to``;
- the ``from`` remainder must not be empty; if it splits, every extra piece
  must be registered under ``drop_parts``/``keep_parts`` for that key;
- the combined area of the pair must not change beyond rounding.

``split`` (map2_2) cuts one included province into two nodes along
``line``. Every violation is ``PATCH_INVALID``:

- ``key`` must resolve to exactly one source province; ``new_key`` and
  ``new_name`` must not collide with existing source geometry (the schema
  already requires ``new_key == new_name.lower()`` and a free key);
- the line must be a valid polyline that crosses the province outline at
  exactly two points, splitting it into exactly two single polygons of at
  least ``_MIN_SPLIT_AREA`` square units each;
- ``keep_point`` must lie inside exactly one part — that part keeps the
  old key (and id); the other part becomes the new node;
- the combined area must not change beyond rounding.
"""
from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split as shapely_split

from .errors import PATCH_INVALID, PipelineError, PipelineFailure
from .models import Overrides, SplitPatch, TransferPatch
from .svg_source import safe_union
from .svgpath import polygons_of

# "sum of areas before/after matches to rounding" — coordinates are kept at
# 0.01 resolution, so the tolerance is one centi-unit squared.
_AREA_TOL = 0.01

# A listed drop/keep point lands inside a remainder part; same buffer as
# pipeline._point_in_part.
_POINT_BUFFER = 0.01

# Minimum area of each half of a ``split`` patch, square base units.
_MIN_SPLIT_AREA = 0.3


def _fail(where: str, message: str) -> PipelineError:
    return PipelineError(PATCH_INVALID, f"{where}: {message}")


def _point_in_part(part: Polygon, point: tuple[float, float]) -> bool:
    return part.buffer(_POINT_BUFFER).contains(Point(point))


def _apply_transfer(
    geoms: dict[str, list[Polygon]],
    by_key: dict[str, list[str]],
    registered: dict[str, list[tuple[float, float]]],
    t: TransferPatch,
    where: str,
) -> str | PipelineError:
    """Apply one ``transfer`` entry; return the INFO line or the error."""
    if t.from_key == t.to_key:
        return _fail(where, "from and to are the same key")
    from_names = by_key.get(t.from_key, [])
    to_names = by_key.get(t.to_key, [])
    if len(from_names) != 1 or len(to_names) != 1:
        return _fail(
            where,
            f"unresolved keys: from={t.from_key!r} "
            f"({len(from_names)} provinces), to={t.to_key!r} "
            f"({len(to_names)} provinces)",
        )
    from_name, to_name = from_names[0], to_names[0]

    poly = Polygon([p.as_tuple() for p in t.polygon])
    if not poly.is_valid or poly.is_empty or poly.area <= 0:
        return _fail(where, "patch polygon is not a valid area")

    old_from = safe_union(geoms[from_name])
    old_to = safe_union(geoms[to_name])
    old_area = old_from.area + old_to.area

    cut = old_from.intersection(poly)
    cut_parts = polygons_of(cut)
    if not cut_parts:
        return _fail(
            where, f"polygon cuts no land out of {from_name!r}"
        )
    if len(cut_parts) > 1:
        return _fail(
            where,
            f"polygon cuts {len(cut_parts)} separate pieces out of "
            f"{from_name!r} (must be exactly one)",
        )
    if not cut_parts[0].intersects(old_to):
        return _fail(where, f"the cut piece does not touch {to_name!r}")

    new_from = old_from.difference(poly)
    rem_parts = polygons_of(new_from)
    if not rem_parts:
        return _fail(where, f"{from_name!r} would be emptied entirely")
    if len(rem_parts) > 1:
        main = max(rem_parts, key=lambda p: (p.area, p.bounds))
        extras = [p for p in rem_parts if p is not main]
        points = registered.get(t.from_key, [])
        uncovered = [
            p
            for p in extras
            if not any(_point_in_part(p, pt) for pt in points)
        ]
        if uncovered:
            return _fail(
                where,
                f"{from_name!r} remainder splits into parts not "
                "listed in drop_parts/keep_parts: "
                + "; ".join(
                    f"area {round(p.area, 4)} near "
                    f"{tuple(round(v, 2) for v in p.representative_point().coords[0])}"
                    for p in uncovered
                ),
            )

    new_to = old_to.union(cut_parts[0])
    to_parts = polygons_of(new_to)
    if len(to_parts) != 1:
        return _fail(
            where,
            f"joining the piece to {to_name!r} leaves "
            f"{len(to_parts)} separate parts",
        )

    new_area = new_from.area + to_parts[0].area
    if abs(new_area - old_area) > _AREA_TOL:
        return _fail(
            where,
            f"area drift {abs(new_area - old_area):.6f} sq. units "
            f"(before {old_area:.4f}, after {new_area:.4f})",
        )

    geoms[from_name] = rem_parts
    geoms[to_name] = to_parts
    return (
        f"moved {round(cut_parts[0].area, 4)} "
        f"sq. units from {from_name!r} to {to_name!r}"
    )


def _line_crossings(boundary, line: LineString) -> int | None:
    """Points where ``line`` meets ``boundary``; ``None`` when the
    intersection is not a plain point set (e.g. a shared segment)."""
    inter = boundary.intersection(line)
    if inter.is_empty:
        return 0
    if inter.geom_type == "Point":
        return 1
    if inter.geom_type == "MultiPoint":
        return len(inter.geoms)
    return None


def _apply_split(
    geoms: dict[str, list[Polygon]],
    by_key: dict[str, list[str]],
    s: SplitPatch,
    where: str,
) -> tuple[str, tuple[str, str]] | PipelineError:
    """Apply one ``split`` entry; return (INFO line, (new_key, new_name)).

    On success ``geoms`` holds the two halves: the old source name keeps
    the part containing ``keep_point``, ``new_name`` is registered with
    the other part (and ``by_key`` learns both assignments).
    """
    names = by_key.get(s.key, [])
    if len(names) != 1:
        return _fail(
            where,
            f"unresolved key {s.key!r} ({len(names)} provinces)",
        )
    name = names[0]
    if s.new_name in geoms or by_key.get(s.new_key):
        return _fail(
            where,
            f"new node {s.new_key!r}/{s.new_name!r} collides with "
            "existing geometry",
        )

    coords = [p.as_tuple() for p in s.line]
    if len(set(coords)) < 2:
        return _fail(where, "split line has no length")
    line = LineString(coords)
    if line.is_empty or line.length <= 0:
        return _fail(where, "split line has no length")

    old = safe_union(geoms[name])
    old_area = old.area

    crossings = _line_crossings(old.boundary, line)
    if crossings != 2:
        detail = (
            "intersection is not a point set (line runs along an edge?)"
            if crossings is None
            else f"{crossings} crossing point(s)"
        )
        return _fail(
            where,
            f"split line must cross the outline of {name!r} at exactly "
            f"two points — got {detail}",
        )

    parts = polygons_of(shapely_split(old, line))
    if len(parts) != 2:
        return _fail(
            where,
            f"splitting {name!r} produced {len(parts)} parts "
            "(must be exactly two single polygons)",
        )
    small = [p for p in parts if p.area < _MIN_SPLIT_AREA]
    if small:
        return _fail(
            where,
            f"split part area {round(small[0].area, 4)} < "
            f"{_MIN_SPLIT_AREA} sq. units",
        )
    if abs(sum(p.area for p in parts) - old_area) > _AREA_TOL:
        return _fail(
            where,
            f"area drift "
            f"{abs(sum(p.area for p in parts) - old_area):.6f} sq. units",
        )

    keep = [_point_in_part(p, s.keep_point.as_tuple()) for p in parts]
    if sum(keep) != 1:
        return _fail(
            where,
            f"keep_point {s.keep_point.as_tuple()} is inside "
            f"{sum(keep)} parts (must be exactly one — a point on the "
            "cut line is ambiguous)",
        )
    keep_part = parts[0] if keep[0] else parts[1]
    new_part = parts[1] if keep[0] else parts[0]

    geoms[name] = [keep_part]
    geoms[s.new_name] = [new_part]
    by_key[s.new_key] = [s.new_name]
    return (
        f"split {name!r}: {round(keep_part.area, 4)} sq. units keep "
        f"{s.key!r}, {round(new_part.area, 4)} sq. units become "
        f"{s.new_key!r} ({s.new_name!r})",
        (s.new_key, s.new_name),
    )


def apply_geometry_patches(
    geoms: dict[str, list[Polygon]], overrides: Overrides
) -> tuple[dict[str, list[Polygon]], list[str], list[tuple[str, str]]]:
    """Apply ``overrides.geometry_patches`` in order; returns new geoms.

    ``geoms`` maps source province names to polygon parts. Keys in a patch
    are slugs (``name.lower()``); an ambiguous or missing slug fails.
    Returns ``(geoms, info_lines, additions)`` where ``additions`` lists
    ``(key, source_name)`` pairs of nodes a ``split`` patch created.
    Raises ``PipelineFailure`` listing every ``PATCH_INVALID`` violation
    found while applying the entries (checks run per entry in order, so an
    earlier failure aborts the batch).
    """
    if not overrides.geometry_patches:
        return geoms, [], []

    geoms = {name: list(parts) for name, parts in geoms.items()}
    by_key: dict[str, list[str]] = {}
    for name in sorted(geoms):
        by_key.setdefault(name.lower(), []).append(name)

    registered: dict[str, list[tuple[float, float]]] = {}
    for entry in (*overrides.drop_parts, *overrides.keep_parts):
        registered.setdefault(entry.key, []).append(entry.point.as_tuple())

    info: list[str] = []
    additions: list[tuple[str, str]] = []
    errors: list[PipelineError] = []
    for i, patch in enumerate(overrides.geometry_patches):
        if patch.transfer is not None:
            where = (
                f"geometry_patches[{i}] transfer "
                f"{patch.transfer.from_key}->{patch.transfer.to_key}"
            )
            res = _apply_transfer(
                geoms, by_key, registered, patch.transfer, where
            )
            if isinstance(res, PipelineError):
                errors.append(res)
            else:
                info.append(f"geometry_patches[{i}]: {res}")
            continue
        s = patch.split
        where = f"geometry_patches[{i}] split {s.key}->{s.new_key}"
        res = _apply_split(geoms, by_key, s, where)
        if isinstance(res, PipelineError):
            errors.append(res)
            continue
        line, added = res
        info.append(f"geometry_patches[{i}]: {line}")
        additions.append(added)

    if errors:
        raise PipelineFailure(errors)
    return geoms, info, additions
