"""map2_10: forced ``land_links`` edges and key renames that keep the id."""
from __future__ import annotations

import json

from conftest import (
    edges_by_key,
    graph_overrides,
    read_graph,
    run_graph,
    square,
)

_ONE_ZONE = [{"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]}]


def _rect(name, x, y, w, h):
    return f'<path id="{name}" d="M {x} {y} h {w} v {h} h {-w} z"/>'


def test_land_links_forces_land_edge(make_data_dir, tmp_path):
    """A and B share a 0.2 border on x=20 — below the global
    ``min_border_length`` (0.3), so no automatic edge appears; a
    ``land_links`` pair forces a ``land`` edge with ``len`` None."""
    data_dir = make_data_dir(
        svg_elems=[
            _rect("A", 10, 14.8, 10, 5.2),
            _rect("B", 20, 10, 10, 5),
        ],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            land_links=[["a", "b"]],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("a", "b")]
    assert edge["type"] == "land"
    assert edge["len"] is None


def test_rename_keeps_id_and_records_previous_key(
    make_data_dir, tmp_path
):
    """``renames`` rewrites key and display name; the locked id
    transfers to the new key and the superseded slug lands in
    ``previous_keys`` (INV-M1: the id never changes)."""
    data_dir = make_data_dir(
        svg_elems=[square("Oldname", 10, 10, 6)],
        include=["Oldname"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            renames=[
                {"from": "oldname", "to": "newname", "name": "New Name"}
            ],
        ),
        lock={"version": 1, "ids": {"oldname": 1001}},
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    node = {n["key"]: n for n in read_graph(out_dir)["nodes"]}["newname"]
    assert node["id"] == 1001
    assert node["name"] == "New Name"
    lock = json.loads((data_dir / "ids.lock.json").read_text())
    assert lock["ids"]["newname"] == 1001
    assert "oldname" not in lock["ids"]
    assert lock["previous_keys"] == {"newname": ["oldname"]}
    # idempotent: a second --check run sees no pending changes
    assert run_graph(data_dir, out_dir, check=True) == 0
