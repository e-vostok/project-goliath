"""drop_parts, keep_parts and ISOLATED_PART scenarios."""
from __future__ import annotations

import json

from conftest import base_overrides, multi_square, square


def test_drop_parts_removes_targeted_part(make_data_dir, run_pipeline):
    # Dual has two parts; the far part touches only an excluded province,
    # so it would be isolated — removing it via drop_parts fixes that.
    elems = [
        multi_square("Dual", [(10, 10, 5), (30, 10, 5)]),
        square("Outland", 35.2, 10, 5),
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Dual"],
        overrides=base_overrides(
            drop_parts=[{"key": "dual", "point": [32.0, 12.0]}]
        ),
    )
    code, out_dir = run_pipeline(data_dir)
    assert code == 0
    nodes = json.loads((out_dir / "land_nodes.json").read_text())
    assert nodes[0]["key"] == "dual"
    assert nodes[0]["parts"] == 1
    assert nodes[0]["area"] == 25.0
    report = (out_dir / "report.md").read_text()
    assert "drop_parts applied: 1" in report
    assert "dual" in report


def test_drop_parts_point_outside(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[multi_square("Dual", [(10, 10, 5), (30, 10, 5)])],
        include=["Dual"],
        overrides=base_overrides(
            drop_parts=[{"key": "dual", "point": [400.0, 400.0]}]
        ),
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "DROP_PART_NOT_FOUND" in capsys.readouterr().err


def test_drop_parts_empties_province(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Solo", 10, 10)],
        include=["Solo"],
        overrides=base_overrides(
            drop_parts=[{"key": "solo", "point": [12.0, 12.0]}]
        ),
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "DROP_PART_EMPTIES_PROVINCE" in capsys.readouterr().err


def test_drop_parts_same_part_twice(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[multi_square("Dual", [(10, 10, 5), (30, 10, 5)])],
        include=["Dual"],
        overrides=base_overrides(
            drop_parts=[
                {"key": "dual", "point": [11.0, 11.0]},
                {"key": "dual", "point": [13.0, 13.0]},
            ]
        ),
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "DATA_INVALID" in capsys.readouterr().err


def test_isolated_part_only_excluded_neighbour(
    make_data_dir, run_pipeline, capsys
):
    elems = [
        multi_square("Dual", [(10, 10, 5), (50, 10, 5)]),
        square("Outland", 55.2, 10, 5),
    ]
    data_dir = make_data_dir(svg_elems=elems, include=["Dual"])
    code, _ = run_pipeline(data_dir)
    assert code == 1
    err = capsys.readouterr().err
    assert "ISOLATED_PART" in err
    assert "key=dual" in err
    assert "Outland" in err


def test_isolated_part_with_included_neighbour_ok(
    make_data_dir, run_pipeline
):
    elems = [
        multi_square("Dual", [(10, 10, 5), (50, 10, 5)]),
        square("Outland", 55.2, 10, 5),
        square("Friend", 50, 15.2, 5),
    ]
    data_dir = make_data_dir(
        svg_elems=elems, include=["Dual", "Friend"]
    )
    code, _ = run_pipeline(data_dir)
    assert code == 0


def test_isolated_part_no_neighbours_ok(make_data_dir, run_pipeline):
    data_dir = make_data_dir(
        svg_elems=[multi_square("Dual", [(10, 10, 5), (400, 400, 5)])],
        include=["Dual"],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 0


def test_isolated_part_whitelisted_by_keep_parts(
    make_data_dir, run_pipeline
):
    elems = [
        multi_square("Dual", [(10, 10, 5), (50, 10, 5)]),
        square("Outland", 55.2, 10, 5),
    ]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Dual"],
        overrides=base_overrides(
            keep_parts=[{"key": "dual", "point": [52.0, 12.0]}]
        ),
    )
    code, _ = run_pipeline(data_dir)
    assert code == 0


def test_isolated_part_below_min_area_ignored(
    make_data_dir, run_pipeline
):
    # Tiny part (0.05x0.05 = 0.0025 < isolated.min_part_area 0.01, but
    # >= clean.min_part_area 0.001) touching only an excluded province.
    elems = [
        multi_square("Dual", [(10, 10, 5), (50, 10, 0.05)]),
        square("Outland", 50.1, 10, 5),
    ]
    data_dir = make_data_dir(svg_elems=elems, include=["Dual"])
    code, _ = run_pipeline(data_dir)
    assert code == 0
