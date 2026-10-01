"""Appendix A step 5: raster frame, band, seeds, water classification."""
from __future__ import annotations

import re

import numpy as np
import pytest

from conftest import (
    graph_overrides,
    kind_at,
    label_at,
    multi_square,
    run_graph,
    sea_raster_meta,
    square,
)


def _ring(prefix, hx, hy, cell=8):
    """8 squares of ``cell`` units enclosing a hole at (hx, hy) of cell size."""
    return [
        square(f"{prefix}{i}{j}", hx - cell + i * cell, hy - cell + j * cell,
               cell)
        for i in (0, 1, 2)
        for j in (0, 1, 2)
        if (i, j) != (1, 1)
    ]


def _ring_keys(prefix):
    return [f"{prefix}{i}{j}" for i in (0, 1, 2) for j in (0, 1, 2)
            if (i, j) != (1, 1)]


def test_frame_and_pixel_convention(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[8.0, 13.0]]}]
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0

    meta = sea_raster_meta(out_dir)
    # playable bbox (10..16)^2 + margin 3 + smooth 0 + extra 1
    assert meta["frame"] == [6.0, 6.0, 20.0, 20.0]
    assert meta["pixels_per_unit"] == 4
    assert meta["width"] == 56
    assert meta["height"] == 56
    assert meta["zone_keys"] == ["sea_a"]
    assert "pixel (col,row)" in meta["pixel_convention"]
    assert kind_at(out_dir, 13.0, 13.0) == 0  # land
    assert kind_at(out_dir, 17.0, 13.0) == 1  # zone water
    assert kind_at(out_dir, 19.75, 13.0) == 2  # beyond the band


def test_band_square_vs_round(make_data_dir, tmp_path):
    """A pixel diagonally off a corner: Chebyshev m labels it, round does not."""
    results = {}
    for shape in ("square", "round"):
        data_dir = make_data_dir(
            svg_elems=[square("Alpha", 10, 10, 6)],
            include=["Alpha"],
            overrides=graph_overrides(
                sea_margin_shape=shape,
                sea_zones=[{"key": "sea_a", "name_ru": "A",
                            "seeds": [[8.0, 13.0]]}],
            ),
        )
        out_dir = tmp_path / shape
        assert run_graph(data_dir, out_dir) == 0
        # (18.75,18.75): Chebyshev pixel distance to the land raster is 3
        # == margin; its Euclidean distance is ~4.2 > 3.
        results[shape] = kind_at(out_dir, 18.75, 18.75)
    assert results["square"] == 1
    assert results["round"] == 2


def test_smooth_closes_notch(make_data_dir, tmp_path):
    """A 1-unit notch in the band closes at smooth=2, stays open at 0."""
    results = {}
    for smooth in (0.0, 2.0):
        data_dir = make_data_dir(
            svg_elems=[square("L", 10, 10, 6), square("R", 20, 10, 6)],
            include=["L", "R"],
            overrides=graph_overrides(
                sea_margin=1.5,
                sea_margin_smooth=smooth,
                sea_zones=[
                    {"key": "sea_a", "name_ru": "A",
                     "seeds": [[8.5, 12.0]]},
                    {"key": "sea_b", "name_ru": "B",
                     "seeds": [[27.5, 12.0]]},
                ],
                straits=[{"a": "l", "b": "r", "name": "St",
                          "multiplier": None}],
            ),
        )
        out_dir = tmp_path / f"s{smooth}"
        assert run_graph(data_dir, out_dir) == 0
        results[smooth] = kind_at(out_dir, 18.0, 13.0)
    assert results[0.0] == 2  # notch: beyond the band of both rings
    assert results[2.0] == 1  # closing merged the band over the slit


def test_seed_on_land_snaps(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[10.5, 13.0]]}]  # 0.5 inside land
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    report = (out_dir / "graph_report.md").read_text()
    m = re.search(r"`sea_a` \(10\.5, 13\.0\) -> pixel .* distance ([\d.]+)",
                  report)
    assert m, report
    assert 0.0 < float(m.group(1)) <= 1.0  # snapped within seed_snap_radius


def test_seed_outside_water(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[11.0, 11.0], [60.0, 60.0]]}]
        ),
    )
    # (11,11) is > snap radius from the edge; (60,60) is off the raster.
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    err = capsys.readouterr().err
    assert "SEED_OUTSIDE_WATER" in err
    # the zone ends up empty too; both errors are collected
    assert "ZONE_EMPTY" in err


def test_seed_outside_band_snaps_to_band_edge(make_data_dir, tmp_path):
    """Seed in water just outside the band snaps onto the band."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[19.5, 13.0]]}]  # 3.5 off land; margin 3
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    report = (out_dir / "graph_report.md").read_text()
    m = re.search(r"`sea_a` \(19\.5, 13\.0\) -> pixel .* distance ([\d.]+)",
                  report)
    assert m, report
    assert 0.0 < float(m.group(1)) <= 1.0


def test_seed_claimed_by_earlier_zone_is_empty(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[8.0, 13.0]]},
            ]
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    err = capsys.readouterr().err
    assert "ZONE_EMPTY" in err
    assert "sea_b" in err


def test_two_seeds_two_bodies_one_zone(make_data_dir, tmp_path):
    """One zone seeding two disjoint water bodies gets two parts."""
    elems = _ring("Xa", 32, 32, cell=8) + _ring("Xb", 72, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("Xa") + _ring_keys("Xb"),
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_o", "name_ru": "O",
                 "seeds": [[21.0, 36.0], [91.0, 36.0]]},
                {"key": "sea_p", "name_ru": "P",
                 "seeds": [[36.0, 36.0], [76.0, 36.0]]},
            ],
            edges_add=[{"a": "sea_o", "b": "sea_p", "type": "sea"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    labels = np.load(out_dir / "sea_labels.npy")
    from scipy import ndimage

    _, n = ndimage.label(
        labels == 2,
        structure=np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]),
    )
    assert n == 2  # two disconnected parts of zone sea_p


def test_drop_part_is_land_and_makes_no_band(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[multi_square("Dual", [(10, 10, 6), (18, 10, 4)])],
        include=["Dual"],
        overrides=graph_overrides(
            sea_margin=6.0,
            drop_parts=[{"key": "dual", "point": [20.0, 12.0]}],
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[17.0, 12.0]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    assert kind_at(out_dir, 20.0, 12.0) == 0  # dropped part counts as land
    assert label_at(out_dir, 17.0, 12.0) == 1  # water near the kept part
    # water next to the dropped part is beyond the band of kept land
    assert kind_at(out_dir, 22.5, 12.0) == 2
    assert label_at(out_dir, 22.5, 12.0) == 0


def test_lake_is_inland_water(make_data_dir, tmp_path):
    elems = _ring("W", 32, 32, cell=6)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("W"),
        overrides=graph_overrides(
            lake_max_area=70.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[24.0, 35.0]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    assert kind_at(out_dir, 35.0, 35.0) == 3  # pond inside the ring is a lake
    assert label_at(out_dir, 35.0, 35.0) == 0
    report = (out_dir / "graph_report.md").read_text()
    assert "Lakes: 1" in report


def test_unseeded_water_is_error(make_data_dir, tmp_path, capsys):
    """Large pond touching the band, no seed, no water_outside -> error."""
    elems = _ring("W", 32, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("W"),
        overrides=graph_overrides(
            lake_max_area=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[21.0, 36.0]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    err = capsys.readouterr().err
    assert "UNSEEDED_WATER" in err
    assert "area=68.0" in err


def test_water_outside_allows_unseeded_body(make_data_dir, tmp_path):
    elems = _ring("W", 32, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("W"),
        overrides=graph_overrides(
            lake_max_area=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[21.0, 36.0]]}],
            water_outside=[{"name": "Pond", "point": [36.0, 36.0]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    assert kind_at(out_dir, 36.0, 36.0) == 2  # unknown sea, not a node
    report = (out_dir / "graph_report.md").read_text()
    assert "Pond: component area 68.0" in report


@pytest.mark.parametrize("point", [[26.0, 26.0], [21.0, 36.0]])
def test_water_outside_invalid(make_data_dir, tmp_path, capsys, point):
    """water_outside on land (26,26) and inside a seeded body (21,36)."""
    elems = _ring("W", 32, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("W"),
        overrides=graph_overrides(
            lake_max_area=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[21.0, 36.0]]}],
            water_outside=[{"name": "Bad", "point": point}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "WATER_OUTSIDE_INVALID" in capsys.readouterr().err


def test_water_outside_invalid_in_lake(make_data_dir, tmp_path, capsys):
    """A water_outside point in a pond below lake_max_area is invalid."""
    elems = _ring("W", 32, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("W"),
        overrides=graph_overrides(
            lake_max_area=70.0,  # pond 64 -> lake
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[21.0, 36.0]]}],
            water_outside=[{"name": "Bad", "point": [36.0, 36.0]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "WATER_OUTSIDE_INVALID" in capsys.readouterr().err


def test_far_water_ignored(make_data_dir, tmp_path):
    """A large unseeded body enclosed by excluded land beyond the band is
    ignored — it never touches the band."""
    elems = [
        square("L", 10, 10, 6),
        square("R", 50, 30, 6),
    ] + _ring("X", 30, 20, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["L", "R"],
        overrides=graph_overrides(
            lake_max_area=30.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[8.0, 13.0]]},
                       {"key": "sea_b", "name_ru": "B",
                        "seeds": [[57.0, 33.0]]}],
            # the two seeded band rings do not touch; a manual edge joins them
            edges_add=[{"a": "sea_a", "b": "sea_b", "type": "sea"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    assert kind_at(out_dir, 34.0, 24.0) == 2  # enclosed pond, not an error


def test_unreached_band_piece_info(make_data_dir, tmp_path):
    """Band water of a seeded body no seed can reach: INFO below the
    lake threshold."""
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 30, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_margin=1.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[8.5, 12.0]]}],
            straits=[{"a": "a", "b": "b", "name": "S",
                      "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    report = (out_dir / "graph_report.md").read_text()
    assert "Unreached band pieces" in report
    assert "1 pieces below lake_max_area" in report


def test_unreached_band_piece_error(make_data_dir, tmp_path, capsys):
    """An unreached band piece at or above lake_max_area is an error."""
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 50, 10, 18)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_margin=1.5,
            lake_max_area=70.0,
            sea_zones=[{"key": "sea_a", "name_ru": "A",
                        "seeds": [[8.5, 12.0]]}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    err = capsys.readouterr().err
    assert "UNSEEDED_WATER" in err
    assert "unreached band piece" in err
