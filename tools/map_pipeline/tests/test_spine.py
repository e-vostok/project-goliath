"""map2_20 label spines: an inscribed chord or gentle arc per node —
inside the territory, along the longest comfortable direction, with
chord length and local thickness for the client fit."""

import math

import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from tools.map_pipeline.geometry import spine_of_node
from tools.map_pipeline.pipeline_config_schema import load_pipeline_config

CFG = load_pipeline_config()


def _arc(spine):
    """Quadratic-Bézier polyline of a NodeSpine in map coordinates."""
    x0, y0, x1, y1, s = spine.spine
    dnx, dny = -(y1 - y0) / spine.len, (x1 - x0) / spine.len
    pts = []
    for i in range(41):
        t = i / 40
        f = 4.0 * s * t * (1.0 - t)
        pts.append(
            (x0 + (x1 - x0) * t + f * dnx, y0 + (y1 - y0) * t + f * dny)
        )
    return LineString(pts)


def _angle(spine) -> float:
    x0, y0, x1, y1, _ = spine.spine
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


def test_spine_square_centred_horizontal_or_diagonal():
    # No preferred direction: any inscribed winner must span the square.
    s = spine_of_node(box(0, 0, 10, 10), CFG)
    assert s.len >= 10.0
    assert s.thick > 0.0
    assert box(0, 0, 10, 10).buffer(0.02).covers(_arc(s))


def test_spine_c_shape_stays_inside_and_out_of_the_notch():
    # C opening to the right (notch = x∈[4,10], y∈[3,7]): the spine
    # must lie inside an arm or the column — a straight chord through
    # the notch would leave the polygon.
    c_shape = Polygon(
        [(0, 0), (10, 0), (10, 3), (4, 3), (4, 7), (10, 7), (10, 10), (0, 10)]
    )
    s = spine_of_node(c_shape, CFG)
    assert c_shape.buffer(0.02).covers(_arc(s))
    assert s.len > 6.0
    # the winner hugs an arm — both endpoints sit outside the notch band
    assert max(s.spine[1], s.spine[3]) < 3.0 or min(s.spine[1], s.spine[3]) > 7.0


def test_spine_diagonal_ellipse_follows_its_angle():
    ell = Polygon(
        [(math.cos(i * 0.2) * 20, math.sin(i * 0.2) * 5) for i in range(32)]
    )
    ell = rotate(ell, 30, origin=(0, 0))
    s = spine_of_node(ell, CFG)
    assert abs(_angle(s) - 30.0) <= CFG.spine.angle_step_deg + 0.5
    assert abs(_angle(s)) <= CFG.spine.max_angle_deg
    assert s.len > 30.0  # long chord through the 40-unit ellipse


def test_spine_steep_ellipse_respects_the_angle_cap():
    # A near-vertical province must not get a steeper baseline than
    # labels.max_angle_deg — the scan is limited by construction.
    ell = Polygon(
        [(math.cos(i * 0.2) * 5, math.sin(i * 0.2) * 20) for i in range(32)]
    )
    s = spine_of_node(ell, CFG)
    assert abs(_angle(s)) <= CFG.spine.max_angle_deg + 1e-6
    assert s.len > 0.0


def test_spine_multipart_uses_the_group_hull():
    # Two equal parts with no dominant one: rule 5 of map2_6 sends the
    # spine to the group's convex hull — the chord spans the gap.
    mp = MultiPolygon([box(0, 0, 5, 5), box(15, 0, 20, 5)])
    s = spine_of_node(mp, CFG)
    assert s.len > 15.0
    assert mp.convex_hull.buffer(0.02).covers(_arc(s))


def test_spine_dominant_part_stays_inside_it():
    big = box(0, 0, 10, 10)
    small = box(20, 0, 22, 2)
    s = spine_of_node(MultiPolygon([big, small]), CFG)
    assert big.buffer(0.02).covers(_arc(s))


def test_spine_small_square_has_a_short_len():
    s = spine_of_node(box(0, 0, 1, 1), CFG)
    assert 0.0 < s.len <= 2.0
    assert s.thick > 0.0


def test_spine_sagitta_within_the_bend_cap():
    # The bend is output as a signed sagitta; |s| must stay under
    # max_bend × len for every node (checked on a curved shape).
    c = Polygon(
        [(0, 0), (10, 0), (10, 3), (4, 3), (4, 7), (10, 7), (10, 10), (0, 10)]
    )
    s = spine_of_node(c, CFG)
    assert abs(s.spine[4]) <= CFG.spine.max_bend * s.len + 0.01
    # a C-arm winner is basically straight
    assert Point(s.spine[0], s.spine[1]).distance(
        Point(s.spine[2], s.spine[3])
    ) == pytest.approx(s.len, abs=0.05)
