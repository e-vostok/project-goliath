"""map2_11: ``transfer_part``/``detach`` patches and the seam-repair step."""
from __future__ import annotations

import json

from conftest import graph_overrides, run_build, run_nodes, square
from tools.map_pipeline.svgpath import parse_path


def _rect(name, x, y, w, h):
    return f'<path id="{name}" d="M {x} {y} h {w} v {h} h {-w} z"/>'


def _multi_rect(name, rects):
    d = " ".join(
        f"M {x} {y} h {w} v {h} h {-w} z" for x, y, w, h in rects
    )
    return f'<path id="{name}" d="{d}"/>'


def test_transfer_part_touching_and_detached(make_data_dir, tmp_path, capsys):
    """A touching cluster merges into one polygon; a detached cluster needs
    ``allow_detached: true`` and otherwise fails with PATCH_INVALID.

    Alpha = mainland + a sliver sharing Beta's edge + a far island.
    """
    svg = [
        _multi_rect(
            "Alpha", [(10, 10, 10, 10), (28, 10, 2, 2), (50, 50, 3, 3)]
        ),
        square("Beta", 30, 10, 10),
    ]
    include = ["Alpha", "Beta"]

    # detached cluster without the flag -> PATCH_INVALID
    data_dir = make_data_dir(
        svg_elems=svg,
        include=include,
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer_part": {
                        "from": "alpha",
                        "cluster_point": [51.0, 51.0],
                        "to": "beta",
                        "allow_detached": False,
                    }
                }
            ],
        ),
    )
    assert run_nodes(data_dir, tmp_path / "out_bad") == 1
    assert "PATCH_INVALID" in capsys.readouterr().err

    # touching sliver merges; the detached island becomes a part of beta
    data_dir = make_data_dir(
        svg_elems=svg,
        include=include,
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "transfer_part": {
                        "from": "alpha",
                        "cluster_point": [29.0, 11.0],
                        "to": "beta",
                        "allow_detached": False,
                    }
                },
                {
                    "transfer_part": {
                        "from": "alpha",
                        "cluster_point": [51.0, 51.0],
                        "to": "beta",
                        "allow_detached": True,
                    }
                },
            ],
        ),
    )
    out_dir = tmp_path / "out_ok"
    assert run_nodes(data_dir, out_dir) == 0
    nodes = {
        n["key"]: n
        for n in json.loads(
            (out_dir / "land_nodes.json").read_text(encoding="utf-8")
        )
    }
    assert nodes["alpha"]["parts"] == 1
    assert nodes["alpha"]["area"] == 100.0
    assert nodes["beta"]["parts"] == 2  # merged mainland + detached island
    assert nodes["beta"]["area"] == 113.0  # 100 + 4 + 9


def test_detach_appends_exactly_one_id(make_data_dir, tmp_path):
    """Two island clusters leave Alpha and form ONE new node; the lock
    gains exactly one id (the next free one)."""
    svg = [
        _multi_rect(
            "Alpha", [(10, 10, 10, 10), (50, 50, 3, 3), (60, 60, 2, 2)]
        ),
        square("Beta", 30, 10, 10),
    ]
    data_dir = make_data_dir(
        svg_elems=svg,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            geometry_patches=[
                {
                    "detach": {
                        "from": "alpha",
                        "cluster_points": [[51.0, 51.0], [61.0, 61.0]],
                        "new_key": "isles",
                        "new_name": "Isles",
                    }
                }
            ],
        ),
        lock={"version": 1, "ids": {"alpha": 1001, "beta": 1002}},
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    nodes = {
        n["key"]: n
        for n in json.loads(
            (out_dir / "land_nodes.json").read_text(encoding="utf-8")
        )
    }
    assert sorted(nodes) == ["alpha", "beta", "isles"]
    assert nodes["isles"]["parts"] == 2
    assert nodes["isles"]["area"] == 13.0
    assert nodes["alpha"]["parts"] == 1
    lock = json.loads((data_dir / "ids.lock.json").read_text())
    assert lock["ids"] == {"alpha": 1001, "beta": 1002, "isles": 1003}


def test_seam_repair_fuses_into_one_ring(make_data_dir, tmp_path):
    """Two rectangles 0.02 apart share a parallel run — the seam scan's
    shape. ``seam_repair`` must leave the node as a single polygon."""
    svg = [
        _multi_rect("Alpha", [(10, 10, 10, 5), (20.02, 10, 5, 5)]),
        square("Beta", 10, 17, 10),
    ]
    data_dir = make_data_dir(
        svg_elems=svg,
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            seam_repair=["alpha"],
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]}
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0
    geom = json.loads((data_dir / "geometry.json").read_text())
    mani = json.loads((data_dir / "manifest.json").read_text())
    node = next(n for n in mani["nodes"] if n["key"] == "alpha")
    parts = parse_path(geom["paths"][str(node["id"])])
    assert len(parts) == 1
    assert len(parts[0].interiors) == 0
