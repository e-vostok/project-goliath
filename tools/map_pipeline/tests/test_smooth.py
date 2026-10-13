"""map2_18: contour smoothing regression — a stair-stepped polygon pair
that shares a border is smoothed pair-consistently, junction vertices
stay put, the area guard holds and a tiny islet is not erased."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon, box

import tools.map_pipeline.smooth as smooth_mod
from tools.map_pipeline.models import Overrides
from tools.map_pipeline.pipeline_config_schema import load_pipeline_config
from tools.map_pipeline.smooth import smooth_land_geometries

from conftest import base_overrides


def _stair_shared() -> list[tuple[float, float]]:
    """Staircase chain from (10, 20) down to (10, 0) — pixel stairs:
    x alternates between 10.0 and 10.1 every 0.1 units of y, a
    ~0.4-unit arc-period sawtooth that sigma=0.10 attenuates strongly."""
    pts = [(10.0, 20.0)]
    y = 20.0
    x = 10.0
    while y > 0.2:
        x = 10.0 if x == 10.1 else 10.1
        pts.append((x, y))
        y -= 0.1
        pts.append((x, y))
    pts += [(10.0, 0.2), (10.0, 0.0)]
    return pts


def _fixture() -> dict:
    shared = _stair_shared()
    geoms = {
        "aaa": Polygon([(0.0, 0.0), (0.0, 20.0), *shared]),
        "bbb": Polygon([(10.0, 0.0), (40.0, 0.0), (40.0, 20.0), *shared]),
        # islet far below small_part_area — must not be erased
        "isl": Polygon(
            [
                (50.0, 50.0),
                (50.05, 50.0),
                (50.05, 50.05),
                (50.0, 50.05),
            ]
        ),
    }
    return geoms


def _shared_stretch(geom) -> LineString:
    """The part of a polygon's boundary along the shared border — the
    box hugs the staircase so only the shared chain survives."""
    # away from the pinned junction ends a sawtooth tooth survives
    # within ~2 sigma — measure the well-interior stretch
    cut = geom.boundary.intersection(box(9.8, 2.0, 10.4, 18.0))
    lines = [g for g in getattr(cut, "geoms", [cut]) if not g.is_empty]
    return max(lines, key=lambda g: g.length)


def test_stair_pair_smoothed_pair_consistent(monkeypatch):
    cfg = load_pipeline_config()
    geoms = _fixture()
    overrides = Overrides.model_validate(base_overrides())
    # the 3 %-kept production guard is meaningless on a 3-ring fixture
    # (the protected islet alone is 33 %) — relax it for the unit test
    monkeypatch.setattr(smooth_mod, "_REVERT_LIMIT", 1.0)

    out, rep = smooth_land_geometries(
        geoms, overrides, frozenset(), (0.0, 0.0, 1200.0, 680.0), cfg
    )

    # the two big rings were smoothed; the islet is either kept or
    # smoothed at the small-part sigma floor — never erased
    assert rep.rings_total == 3
    assert rep.rings_smoothed >= 2
    assert rep.rings_kept <= 1

    # graph identity: same node keys, same part counts
    assert sorted(out) == sorted(geoms)

    for key in ("aaa", "bbb"):
        old, new = geoms[key], out[key]
        assert new.is_valid
        # area change inside the configured limit
        rel = abs(new.area - old.area) / old.area
        assert rel <= cfg.smooth.max_area_change
        # junction vertices (10,0) and (10,20) did not move — they are
        # still exact vertices of the new boundary
        for jx, jy in ((10.0, 0.0), (10.0, 20.0)):
            assert new.boundary.distance(Point(jx, jy)) == pytest.approx(
                0.0, abs=1e-6
            )

    # the shared stretch stays within 0.05 of the other side
    a_side = _shared_stretch(out["aaa"])
    b_side = _shared_stretch(out["bbb"])
    assert a_side.distance(b_side) <= 0.05

    # the stairs are gone: the smoothed shared stretch deviates far
    # less from the x=10.1 midline than the 0.2-wide sawtooth did
    xs = [p[0] for p in a_side.coords]
    assert max(xs) - min(xs) < 0.06  # was a 0.1-wide sawtooth

    # the tiny islet was not erased
    assert out["isl"].is_valid
    assert out["isl"].area > 0.5 * geoms["isl"].area


def test_guard_rail_report_fields(monkeypatch):
    cfg = load_pipeline_config()
    geoms = _fixture()
    overrides = Overrides.model_validate(base_overrides())
    monkeypatch.setattr(smooth_mod, "_REVERT_LIMIT", 1.0)
    _out, rep = smooth_land_geometries(
        geoms, overrides, frozenset(), (0.0, 0.0, 1200.0, 680.0), cfg
    )
    assert rep.max_displacement <= cfg.smooth.max_displacement
    assert rep.max_area_change <= cfg.smooth.max_area_change * 4
    # every measured pair row is within the seam-cover limit
    for _a, _b, gap, _gap0 in rep.worst_gap:
        assert gap <= 0.05
