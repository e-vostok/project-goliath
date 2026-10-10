"""map2_1B: canonical shared borders/coasts on a three-province mini map."""
from __future__ import annotations

from shapely.geometry import Polygon

from tools.map_pipeline.borders import build_borders
from tools.map_pipeline.borders_proto.compute import LandNode
from tools.map_pipeline.pipeline_config_schema import load_pipeline_config


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _nodes(size: float = 10.0) -> dict[int, LandNode]:
    """Three provinces meeting at the single point (size, size)."""
    return {
        1: LandNode(1, "west", _square(0, 0, size, size), [2, 3]),
        2: LandNode(
            2, "east", _square(size, 0, 2 * size, size), [1, 3]
        ),
        3: LandNode(
            3, "north", _square(0, size, 2 * size, 2 * size), [1, 2]
        ),
    }


_EDGES = [(1, 2), (1, 3), (2, 3)]


def test_borders_three_provinces_meeting_at_point():
    cfg = load_pipeline_config()
    res = build_borders(_nodes(), _EDGES, "0123456789ab", cfg)
    doc = res.doc

    # one canonical border line per pair, one coast path per node
    assert set(doc["pairs"]) == {"1-2", "1-3", "2-3"}
    assert set(doc["coasts"]) == {"1", "2", "3"}
    assert res.pair_count == 3
    assert res.coast_count == 3
    for d in (*doc["pairs"].values(), *doc["coasts"].values()):
        assert d.startswith("M "), d
    assert doc["version"] == res.doc["version"]

    # the borders version takes the geometry version as an input
    other = build_borders(_nodes(), _EDGES, "ffffffffffff", cfg)
    assert other.doc["version"] != doc["version"]

    # and the emitted lines themselves — same geometry_version but
    # different geometry still re-versions the file
    resized = build_borders(_nodes(size=11.0), _EDGES, "0123456789ab", cfg)
    assert resized.doc["version"] != doc["version"]
