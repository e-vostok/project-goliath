"""Spec 1.9 additions: geometry_patches (transfer) and retired sea zones."""
from __future__ import annotations

import json

from conftest import (
    graph_overrides,
    kind_at,
    label_at,
    read_graph,
    run_graph,
    run_nodes,
    square,
)


def test_transfer_patch_moves_land_to_included(make_data_dir, tmp_path):
    """A strip of excluded Beta next to Alpha becomes Alpha's land.

    Gamma keeps Alpha from tripping ISOLATED_PART (a playable province
    needs at least one playable neighbour).
    """
    data_dir = make_data_dir(
        svg_elems=[
            square("Alpha", 10, 10, 10),
            square("Beta", 20, 10, 10),
            square("Gamma", 10, 20, 10),
        ],
        include=["Alpha", "Gamma"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [20.0, 10.0], [25.0, 10.0],
                            [25.0, 20.0], [20.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    nodes = {
        n["key"]: n
        for n in json.loads(
            (out_dir / "land_nodes.json").read_text(encoding="utf-8")
        )
    }
    assert sorted(nodes) == ["alpha", "gamma"]
    assert nodes["alpha"]["area"] == 150.0  # 100 + the transferred 50


def test_transfer_patch_from_and_to_both_included(make_data_dir, tmp_path):
    """The same shape works while both provinces stay in the game."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10), square("Beta", 20, 10, 10)],
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [20.0, 10.0], [25.0, 10.0],
                            [25.0, 20.0], [20.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    nodes = {
        n["key"]: n
        for n in json.loads(
            (out_dir / "land_nodes.json").read_text(encoding="utf-8")
        )
    }
    assert nodes["alpha"]["area"] == 150.0
    assert nodes["beta"]["area"] == 50.0


def test_patch_unknown_key_is_data_invalid(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10)],
        include=["Alpha"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [20.0, 10.0], [25.0, 10.0], [25.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    assert "DATA_INVALID" in capsys.readouterr().err


def test_patch_to_excluded_is_data_invalid(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10), square("Beta", 20, 10, 10)],
        include=["Alpha"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "alpha",
                        "to": "beta",
                        "polygon": [
                            [15.0, 10.0], [20.0, 10.0], [20.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "DATA_INVALID" in err
    assert "excluded" in err


def test_patch_cuts_nothing(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10), square("Beta", 20, 10, 10)],
        include=["Alpha"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [40.0, 40.0], [45.0, 40.0], [45.0, 45.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "PATCH_INVALID" in err
    assert "cuts no land" in err


def test_patch_cut_does_not_touch_to(make_data_dir, tmp_path, capsys):
    """The piece must adjoin the receiving province."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10), square("Beta", 30, 10, 10)],
        include=["Alpha"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [30.0, 10.0], [35.0, 10.0],
                            [35.0, 20.0], [30.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "PATCH_INVALID" in err
    assert "does not touch" in err


def test_patch_empties_from(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 10), square("Beta", 20, 10, 10)],
        include=["Alpha"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [20.0, 10.0], [30.0, 10.0],
                            [30.0, 20.0], [20.0, 20.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "PATCH_INVALID" in err
    assert "emptied entirely" in err


def test_patch_remainder_splits_unregistered(make_data_dir, tmp_path, capsys):
    """A strip cut through the middle leaves Beta in two unlisted parts."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 20, 10), square("Beta", 10, 10, 10)],
        include=["Alpha"],
        exclude=["Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [13.0, 10.0], [17.0, 10.0],
                            [17.0, 21.0], [13.0, 21.0],
                        ],
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    err = capsys.readouterr().err
    assert "PATCH_INVALID" in err
    assert "drop_parts/keep_parts" in err


def test_patch_remainder_split_registered(make_data_dir, tmp_path):
    """The same split passes when the spare part is in keep_parts."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 20, 10), square("Beta", 10, 10, 10)],
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            # the larger-bounds remainder part is the main body; the spare
            # left strip must be registered explicitly
            keep_parts=[{"key": "beta", "point": [11.5, 15.0]}],
            geometry_patches=[
                {
                    "transfer": {
                        "from": "beta",
                        "to": "alpha",
                        "polygon": [
                            [13.0, 10.0], [17.0, 10.0],
                            [17.0, 21.0], [13.0, 21.0],
                        ],
                    }
                }
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    nodes = {
        n["key"]: n
        for n in json.loads(
            (out_dir / "land_nodes.json").read_text(encoding="utf-8")
        )
    }
    assert nodes["beta"]["parts"] == 2
    assert nodes["alpha"]["area"] == 140.0


def test_retired_sea_zone_no_node_no_edges(make_data_dir, tmp_path):
    """Retired zone: water keeps its label, no node, kind = unknown sea."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6), square("Beta", 16, 10, 6)],
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {
                    "key": "sea_b",
                    "name_ru": "B",
                    "seeds": [[24.0, 13.0]],
                    "retired": True,
                },
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0

    graph = read_graph(out_dir)
    keys = {n["key"] for n in graph["nodes"]}
    assert keys == {"alpha", "beta", "sea_a"}
    by_key = {}
    for e in graph["edges"]:
        a, b = sorted(
            (next(n["key"] for n in graph["nodes"] if n["id"] == e["a"]),
             next(n["key"] for n in graph["nodes"] if n["id"] == e["b"]))
        )
        by_key[(a, b)] = e["type"]
    assert by_key.get(("alpha", "beta")) == "land"
    assert all("sea_b" not in pair for pair in by_key)

    assert label_at(out_dir, 24.0, 13.0) == 2  # label survives
    assert kind_at(out_dir, 24.0, 13.0) == 2  # but reads as unknown sea
    assert label_at(out_dir, 8.0, 13.0) == 1
    assert kind_at(out_dir, 8.0, 13.0) == 1

    report = (out_dir / "graph_report.md").read_text(encoding="utf-8")
    assert "retired" in report
    assert "`sea_b` — retired (no node)" in report


def test_retired_zone_needs_no_reachable_seed(make_data_dir, tmp_path):
    """A retired zone's seed may land outside any working water."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {
                    "key": "sea_far",
                    "name_ru": "F",
                    "seeds": [[400.0, 400.0]],
                    "retired": True,
                },
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    keys = {n["key"] for n in read_graph(out_dir)["nodes"]}
    assert keys == {"alpha", "sea_a"}


def test_coastless_section_present_in_report(make_data_dir, tmp_path):
    """The report always carries the coast-less sea-zone section."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    report = (out_dir / "graph_report.md").read_text()
    assert "Sea zones without a coast edge" in report
    assert "- none" in report


def test_lock_retains_excluded_and_retired_keys(make_data_dir, tmp_path):
    """ids.lock.json keeps excluded-land and retired-sea ids (INV-M1)."""
    lock = {
        "version": 1,
        "ids": {
            "alpha": 1001,
            "beta": 1002,
            "sea_a": 1003,
            "sea_b": 1004,
        },
    }
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6), square("Beta", 16, 10, 6)],
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {
                    "key": "sea_b",
                    "name_ru": "B",
                    "seeds": [[24.0, 13.0]],
                    "retired": True,
                },
            ],
        ),
        lock=lock,
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    new_lock = json.loads(
        (data_dir / "ids.lock.json").read_text(encoding="utf-8")
    )
    assert new_lock["ids"] == lock["ids"]


def test_lock_retains_exclude_explicit_keys(make_data_dir, tmp_path):
    """A province moved to exclude_explicit keeps its id in the lock."""
    lock = {"version": 1, "ids": {"alpha": 1001, "beta": 1002, "gamma": 1005}}
    data_dir = make_data_dir(
        svg_elems=[
            square("Alpha", 10, 10, 6),
            square("Beta", 16, 10, 6),
            square("Gamma", 10, 16, 6),
        ],
        include=["Alpha", "Gamma"],
        exclude=["Beta"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
            ],
        ),
        lock=lock,
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    new_lock = json.loads(
        (data_dir / "ids.lock.json").read_text(encoding="utf-8")
    )
    assert new_lock["ids"]["beta"] == 1002


def test_lock_key_removed_still_fails(make_data_dir, tmp_path, capsys):
    """A lock key absent from both include and exclude is KEY_REMOVED."""
    lock = {"version": 1, "ids": {"alpha": 1001, "gamma": 1003}}
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        lock=lock,
    )
    assert run_nodes(data_dir, tmp_path / "out") == 1
    assert "KEY_REMOVED" in capsys.readouterr().err
