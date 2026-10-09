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

``transfer_part`` (map2_11) moves a whole cluster of ``from`` — the set of
parts connected through gaps smaller than ``_PART_GAP`` units that contains
``cluster_point`` — to ``to``. ``detach`` lifts the clusters selected by
``cluster_points`` out of ``from`` and forms one new node from them. Both
keep ``from`` non-empty and conserve the total area; every violation is
``PATCH_INVALID``. ``transfer_part`` and ``detach`` are keyed by the
current node keys (post-``renames``), resolved back to source geometry.
"""
from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split as shapely_split

from .errors import PATCH_INVALID, PipelineError, PipelineFailure
from .models import (
    DetachPatch,
    Overrides,
    SplitPatch,
    TransferPartPatch,
    TransferPatch,
)
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

# Parts whose boundaries are closer than this belong to one cluster —
# the definition of sheet «Куски» in map_fixes_table.xlsx (map2_11).
_PART_GAP = 0.5


def _fail(where: str, message: str) -> PipelineError:
    return PipelineError(PATCH_INVALID, f"{where}: {message}")


def _point_in_part(part: Polygon, point: tuple[float, float]) -> bool:
    return part.buffer(_POINT_BUFFER).contains(Point(point))


def _part_clusters(parts: list[Polygon]) -> list[list[int]]:
    """Connected components of parts linked through gaps < ``_PART_GAP``.

    Returns groups of part indices (map2_11 «Куски» definition).
    """
    parent = list(range(len(parts)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            if parts[i].distance(parts[j]) < _PART_GAP:
                pi, pj = _find(i), _find(j)
                if pi != pj:
                    parent[pi] = pj
    groups: dict[int, list[int]] = {}
    for i in range(len(parts)):
        groups.setdefault(_find(i), []).append(i)
    return list(groups.values())


def _cluster_at(
    parts: list[Polygon],
    clusters: list[list[int]],
    point: tuple[float, float],
) -> list[int] | None:
    """The cluster whose part covers ``point``; ``None`` when the point
    falls into no part."""
    for group in clusters:
        if any(_point_in_part(parts[i], point) for i in group):
            return group
    return None


def _apply_transfer_part(
    geoms: dict[str, list[Polygon]],
    by_key: dict[str, list[str]],
    t: TransferPartPatch,
    where: str,
) -> str | PipelineError:
    """Apply one ``transfer_part`` entry; return the INFO line or error.

    The cluster of ``from`` holding ``cluster_point`` moves to ``to``.
    A touching cluster must merge into a single ``to`` polygon; a
    detached one needs ``allow_detached: true``.
    """
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
    if from_name == to_name:
        return _fail(where, "from and to resolve to the same province")

    parts = geoms[from_name]
    cluster = _cluster_at(parts, _part_clusters(parts), t.cluster_point.as_tuple())
    if cluster is None:
        return _fail(
            where,
            f"cluster_point {t.cluster_point.as_tuple()} falls into no "
            f"part of {from_name!r}",
        )
    rest = [p for i, p in enumerate(parts) if i not in cluster]
    if not rest:
        return _fail(where, f"{from_name!r} would be emptied entirely")

    moved = [parts[i] for i in cluster]
    old_to = safe_union(geoms[to_name])
    old_area = sum(p.area for p in parts) + old_to.area
    moved_u = safe_union(moved)

    if moved_u.intersects(old_to):
        to_parts = polygons_of(old_to.union(moved_u))
        if len(to_parts) != 1:
            return _fail(
                where,
                f"joining the cluster to {to_name!r} leaves "
                f"{len(to_parts)} separate parts",
            )
    else:
        if not t.allow_detached:
            return _fail(
                where,
                f"the cluster does not touch {to_name!r} "
                "(needs allow_detached: true)",
            )
        to_parts = [*geoms[to_name], *moved]

    new_area = sum(p.area for p in rest) + sum(p.area for p in to_parts)
    if abs(new_area - old_area) > _AREA_TOL:
        return _fail(
            where,
            f"area drift {abs(new_area - old_area):.6f} sq. units "
            f"(before {old_area:.4f}, after {new_area:.4f})",
        )

    geoms[from_name] = rest
    geoms[to_name] = to_parts
    return (
        f"moved cluster of {len(moved)} part(s), "
        f"{round(moved_u.area, 4)} sq. units, from {from_name!r} "
        f"to {to_name!r}"
    )


def _apply_detach(
    geoms: dict[str, list[Polygon]],
    by_key: dict[str, list[str]],
    d: DetachPatch,
    where: str,
) -> tuple[str, tuple[str, str]] | PipelineError:
    """Apply one ``detach`` entry; return (INFO line, (new_key, new_name)).

    Every ``cluster_points`` entry selects one cluster of ``from``; the
    selected clusters leave ``from`` together and become the parts of the
    new node ``new_name`` (registered under ``new_key``).
    """
    names = by_key.get(d.from_key, [])
    if len(names) != 1:
        return _fail(
            where,
            f"unresolved key {d.from_key!r} ({len(names)} provinces)",
        )
    name = names[0]
    if d.new_name in geoms or by_key.get(d.new_key):
        return _fail(
            where,
            f"new node {d.new_key!r}/{d.new_name!r} collides with "
            "existing geometry",
        )

    parts = geoms[name]
    clusters = _part_clusters(parts)
    taken: set[int] = set()
    for pt in d.cluster_points:
        group = _cluster_at(parts, clusters, pt.as_tuple())
        if group is None:
            return _fail(
                where,
                f"cluster_point {pt.as_tuple()} falls into no part "
                f"of {name!r}",
            )
        if any(i in taken for i in group):
            return _fail(
                where,
                f"two cluster_points select the same cluster of "
                f"{name!r} (point {pt.as_tuple()})",
            )
        taken.update(group)

    detached = [parts[i] for i in sorted(taken)]
    rest = [p for i, p in enumerate(parts) if i not in taken]
    if not rest:
        return _fail(where, f"{name!r} would be emptied entirely")

    old_area = sum(p.area for p in parts)
    new_area = sum(p.area for p in rest) + sum(p.area for p in detached)
    if abs(new_area - old_area) > _AREA_TOL:
        return _fail(
            where,
            f"area drift {abs(new_area - old_area):.6f} sq. units",
        )

    geoms[name] = rest
    geoms[d.new_name] = detached
    by_key[d.new_key] = [d.new_name]
    return (
        f"detached {len(detached)} part(s), "
        f"{round(sum(p.area for p in detached), 4)} sq. units, from "
        f"{name!r} into new node {d.new_key!r} ({d.new_name!r})",
        (d.new_key, d.new_name),
    )


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
    ``(key, source_name)`` pairs of nodes a ``split`` or ``detach`` patch
    created.
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
    # map2_11: transfer_part/detach are written with the CURRENT node keys,
    # so a rename target resolves back to its source geometry as well.
    for r in overrides.renames:
        src = by_key.get(r.from_key, [])
        if len(src) == 1 and r.to_key not in by_key:
            by_key[r.to_key] = src

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
        tp = patch.transfer_part
        if tp is not None:
            where = (
                f"geometry_patches[{i}] transfer_part "
                f"{tp.from_key}->{tp.to_key}"
            )
            res = _apply_transfer_part(geoms, by_key, tp, where)
            if isinstance(res, PipelineError):
                errors.append(res)
            else:
                info.append(f"geometry_patches[{i}]: {res}")
            continue
        d = patch.detach
        if d is not None:
            where = (
                f"geometry_patches[{i}] detach "
                f"{d.from_key}->{d.new_key}"
            )
            res = _apply_detach(geoms, by_key, d, where)
            if isinstance(res, PipelineError):
                errors.append(res)
                continue
            line, added = res
            info.append(f"geometry_patches[{i}]: {line}")
            additions.append(added)
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
