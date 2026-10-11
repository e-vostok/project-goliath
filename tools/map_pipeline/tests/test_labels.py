"""map2_6 label boxes: pole-of-inaccessibility anchor for a dominant
part, area-weighted centre for a scattered multi-part node, positive
w/h always."""

import pytest
from shapely.geometry import MultiPolygon, Point, Polygon, box

from tools.map_pipeline.geometry import label_box

GRID = 0.01


def test_label_box_c_shape_anchor_inside_dominant_part():
    # C opening to the right: the pole sits in the thick left column,
    # not in the mouth — and every single-part anchor must be inside.
    c_shape = Polygon(
        [(0, 0), (10, 0), (10, 3), (4, 3), (4, 7), (10, 7), (10, 10), (0, 10)]
    )
    x, y, w, h = label_box(c_shape, GRID)
    assert c_shape.covers(Point(x, y))
    assert w > 0 and h > 0
    assert x <= 4.0


def test_label_box_multipart_weighted_centre():
    parts = MultiPolygon([box(0, 0, 2, 2), box(10, 0, 12, 2)])
    x, y, w, h = label_box(parts, GRID)
    assert (x, y) == (6.0, 1.0)  # area-weighted centre of two equal parts
    assert w == pytest.approx(0.9 * 12)  # 0.9 × group bbox
    assert h == pytest.approx(0.9 * 2)


def test_label_box_dominant_part_of_multipart():
    # One part holds > 60% of the area → anchor is inside THAT part.
    big = box(0, 0, 10, 10)
    small = box(20, 0, 22, 2)
    x, y, w, h = label_box(MultiPolygon([big, small]), GRID)
    assert big.covers(Point(x, y))
    assert w > 0 and h > 0
