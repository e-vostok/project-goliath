"""Steps 1–4 behaviour on small real SVG fixtures (no mocks)."""
from __future__ import annotations

import json

import pytest
import yaml

from tools.map_pipeline.models import Boundary, Overrides
from tools.map_pipeline.pipeline import _select_nodes

from conftest import base_overrides, multi_square, run_nodes, square


def test_happy_path(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[
            square("Alpha", 10, 10),
            square("Beta", 30, 10),
            square("Gamma", 50, 10),
            multi_square("Delta_Two", [(70, 10, 5), (90, 10, 5)]),
            square("Epsilon", 110, 10),
        ],
        include=["Alpha", "Beta", "Gamma", "Delta_Two", "Epsilon"],
        defs_elems=[
            '<path id="pattern0" d="M 0 0 h 2 v 2 h -2 z"/>',
            '<path id="pattern0" d="M 0 0 h 3 v 3 h -3 z"/>',
        ],
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0

    nodes = json.loads((out_dir / "land_nodes.json").read_text())
    assert [n["id"] for n in nodes] == [1001, 1002, 1003, 1004, 1005]
    # ids are assigned in ascending key order
    assert [n["key"] for n in nodes] == [
        "alpha",
        "beta",
        "delta_two",
        "epsilon",
        "gamma",
    ]
    by_key = {n["key"]: n for n in nodes}
    assert by_key["delta_two"]["parts"] == 2
    assert by_key["delta_two"]["source_name"] == "Delta_Two"
    assert by_key["alpha"]["area"] == 25.0

    lock = json.loads((data_dir / "ids.lock.json").read_text())
    assert lock["ids"]["alpha"] == 1001

    report = (out_dir / "report.md").read_text()
    assert "Multi-part provinces: 1" in report
    assert "1001..1005" in report

    # second run is byte-identical (report legitimately differs: no new ids)
    nodes_bytes = (out_dir / "land_nodes.json").read_bytes()
    lock_bytes = (data_dir / "ids.lock.json").read_bytes()
    assert run_nodes(data_dir, out_dir) == 0
    assert (out_dir / "land_nodes.json").read_bytes() == nodes_bytes
    assert (data_dir / "ids.lock.json").read_bytes() == lock_bytes
    report2 = (out_dir / "report.md").read_text()
    assert "New ids assigned: none" in report2


def test_duplicate_id(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10), square("Alpha", 30, 10)],
        include=["Alpha"],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "DUPLICATE_ID" in capsys.readouterr().err


def test_pattern_duplicates_in_defs_ignored(
    make_data_dir, run_pipeline
):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10)],
        include=["Alpha"],
        defs_elems=[
            '<path id="pattern0" d="M 0 0 h 2 v 2 h -2 z"/>',
            '<path id="pattern0" d="M 0 0 h 3 v 3 h -3 z"/>',
        ],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 0


def test_unsupported_transform(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[
            '<g transform="scale(2)">'
            '<path id="Alpha" d="M 10 10 h 5 v 5 h -5 z"/>'
            "</g>"
        ],
        include=["Alpha"],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "UNSUPPORTED_TRANSFORM" in capsys.readouterr().err


def test_boundary_unknown_id(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10)],
        include=["Alpha", "Ghost"],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    err = capsys.readouterr().err
    assert "BOUNDARY_UNKNOWN_ID" in err
    assert "Ghost" in err


def test_key_invalid():
    # KEY_INVALID is unreachable through a schema-valid boundary.yaml (names
    # are ^[A-Za-z0-9_]+$ and always lowercase cleanly); exercise it directly.
    boundary = Boundary.model_construct(
        include=["Foo-Bar"], exclude_explicit=[]
    )
    overrides = Overrides.model_construct(technical_exclude=[])
    with pytest.raises(Exception) as ei:
        _select_nodes({"Foo-Bar": "M 0 0"}, boundary, overrides)
    assert ei.value.errors[0].code == "KEY_INVALID"


def test_key_collision(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Ab_c", 10, 10), square("ab_C", 30, 10)],
        include=["Ab_c", "ab_C"],
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "KEY_COLLISION" in capsys.readouterr().err


def test_technical_exclude_not_in_include_is_info(
    make_data_dir, run_pipeline
):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10)],
        include=["Alpha"],
        overrides=base_overrides(technical_exclude=["ghost"]),
    )
    code, out_dir = run_pipeline(data_dir)
    assert code == 0
    assert "ghost" in (out_dir / "report.md").read_text()


def test_technical_exclude_ignored_as_neighbour(
    make_data_dir, run_pipeline, capsys
):
    # An included islet whose only neighbour is a technical_exclude province
    # has effectively no neighbours -> fine. Without the exclusion the same
    # islet is an ISOLATED_PART error.
    elems = [square("Islet", 50, 50), square("Junk", 44.9, 50, 5)]
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Islet"],
        overrides=base_overrides(technical_exclude=["junk"]),
    )
    code, _ = run_pipeline(data_dir)
    assert code == 0

    data_dir2 = make_data_dir(svg_elems=elems, include=["Islet"])
    code2, _ = run_pipeline(data_dir2)
    assert code2 == 1
    assert "ISOLATED_PART" in capsys.readouterr().err
