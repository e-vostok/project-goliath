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
"""
from __future__ import annotations

from shapely.geometry import Point, Polygon

from .errors import PATCH_INVALID, PipelineError, PipelineFailure
from .models import Overrides
from .svg_source import safe_union
from .svgpath import polygons_of

# "sum of areas before/after matches to rounding" — coordinates are kept at
# 0.01 resolution, so the tolerance is one centi-unit squared.
_AREA_TOL = 0.01

# A listed drop/keep point lands inside a remainder part; same buffer as
# pipeline._point_in_part.
_POINT_BUFFER = 0.01


def _fail(where: str, message: str) -> PipelineError:
    return PipelineError(PATCH_INVALID, f"{where}: {message}")


def _point_in_part(part: Polygon, point: tuple[float, float]) -> bool:
    return part.buffer(_POINT_BUFFER).contains(Point(point))


def apply_geometry_patches(
    geoms: dict[str, list[Polygon]], overrides: Overrides
) -> tuple[dict[str, list[Polygon]], list[str]]:
    """Apply ``overrides.geometry_patches`` in order; returns new geoms.

    ``geoms`` maps source province names to polygon parts. Keys in the patch
    are slugs (``name.lower()``); an ambiguous or missing slug fails. Returns
    ``(geoms, info_lines)``; raises ``PipelineFailure`` listing every
    ``PATCH_INVALID`` violation found while applying the entries (checks run
    per entry in order, so an earlier failure aborts the batch).
    """
    if not overrides.geometry_patches:
        return geoms, []

    geoms = {name: list(parts) for name, parts in geoms.items()}
    by_key: dict[str, list[str]] = {}
    for name in sorted(geoms):
        by_key.setdefault(name.lower(), []).append(name)

    registered: dict[str, list[tuple[float, float]]] = {}
    for entry in (*overrides.drop_parts, *overrides.keep_parts):
        registered.setdefault(entry.key, []).append(entry.point.as_tuple())

    info: list[str] = []
    errors: list[PipelineError] = []
    for i, patch in enumerate(overrides.geometry_patches):
        t = patch.transfer
        where = f"geometry_patches[{i}] transfer {t.from_key}->{t.to_key}"
        if t.from_key == t.to_key:
            errors.append(_fail(where, "from and to are the same key"))
            continue
        from_names = by_key.get(t.from_key, [])
        to_names = by_key.get(t.to_key, [])
        if len(from_names) != 1 or len(to_names) != 1:
            errors.append(
                _fail(
                    where,
                    f"unresolved keys: from={t.from_key!r} "
                    f"({len(from_names)} provinces), to={t.to_key!r} "
                    f"({len(to_names)} provinces)",
                )
            )
            continue
        from_name, to_name = from_names[0], to_names[0]

        poly = Polygon([p.as_tuple() for p in t.polygon])
        if not poly.is_valid or poly.is_empty or poly.area <= 0:
            errors.append(_fail(where, "patch polygon is not a valid area"))
            continue

        old_from = safe_union(geoms[from_name])
        old_to = safe_union(geoms[to_name])
        old_area = old_from.area + old_to.area

        cut = old_from.intersection(poly)
        cut_parts = polygons_of(cut)
        if not cut_parts:
            errors.append(
                _fail(where, "polygon cuts no land out of "
                             f"{from_name!r}")
            )
            continue
        if len(cut_parts) > 1:
            errors.append(
                _fail(
                    where,
                    f"polygon cuts {len(cut_parts)} separate pieces out of "
                    f"{from_name!r} (must be exactly one)",
                )
            )
            continue
        if not cut_parts[0].intersects(old_to):
            errors.append(
                _fail(where, f"the cut piece does not touch {to_name!r}")
            )
            continue

        new_from = old_from.difference(poly)
        rem_parts = polygons_of(new_from)
        if not rem_parts:
            errors.append(
                _fail(where, f"{from_name!r} would be emptied entirely")
            )
            continue
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
                errors.append(
                    _fail(
                        where,
                        f"{from_name!r} remainder splits into parts not "
                        "listed in drop_parts/keep_parts: "
                        + "; ".join(
                            f"area {round(p.area, 4)} near "
                            f"{tuple(round(v, 2) for v in p.representative_point().coords[0])}"
                            for p in uncovered
                        ),
                    )
                )
                continue

        new_to = old_to.union(cut_parts[0])
        to_parts = polygons_of(new_to)
        if len(to_parts) != 1:
            errors.append(
                _fail(
                    where,
                    f"joining the piece to {to_name!r} leaves "
                    f"{len(to_parts)} separate parts",
                )
            )
            continue

        new_area = new_from.area + to_parts[0].area
        if abs(new_area - old_area) > _AREA_TOL:
            errors.append(
                _fail(
                    where,
                    f"area drift {abs(new_area - old_area):.6f} sq. units "
                    f"(before {old_area:.4f}, after {new_area:.4f})",
                )
            )
            continue

        geoms[from_name] = rem_parts
        geoms[to_name] = to_parts
        info.append(
            f"geometry_patches[{i}]: moved {round(cut_parts[0].area, 4)} "
            f"sq. units from {from_name!r} to {to_name!r}"
        )

    if errors:
        raise PipelineFailure(errors)
    return geoms, info
