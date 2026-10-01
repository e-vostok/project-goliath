"""Appendix A step 6: graph edges, overrides, straits, invariants."""
from __future__ import annotations

import numpy as np

from conftest import (
    edges_by_key,
    graph_overrides,
    label_at,
    read_graph,
    run_graph,
    square,
)

_ONE_ZONE = [{"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]}]


def _rect(name, x, y, w, h):
    return f'<path id="{name}" d="M {x} {y} h {w} v {h} h {-w} z"/>'


def _ring(prefix, hx, hy, cell=8):
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


def test_land_edge_shared_side(make_data_dir, tmp_path):
    """A [10,20]x[14.5,20] and B [20,30]x[10,15] share 0.5 of x=20."""
    data_dir = make_data_dir(
        svg_elems=[_rect("A", 10, 14.5, 10, 5.5), _rect("B", 20, 10, 10, 5)],
        include=["A", "B"],
        overrides=graph_overrides(sea_zones=_ONE_ZONE),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("a", "b")]
    assert edge["type"] == "land"
    assert 0.4 < edge["len"] < 0.7  # ~0.5


def test_land_edge_below_min_length(make_data_dir, tmp_path):
    """Same layout with a shared side of 0.2 < min_border_length: no edge."""
    data_dir = make_data_dir(
        svg_elems=[_rect("A", 10, 14.8, 10, 5.2), _rect("B", 20, 10, 10, 5)],
        include=["A", "B"],
        overrides=graph_overrides(sea_zones=_ONE_ZONE),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edges = edges_by_key(read_graph(out_dir))
    assert ("a", "b") not in edges
    # both nodes still have coast edges to the zone -> graph connected
    assert ("a", "sea_a") in edges
    assert ("b", "sea_a") in edges


def test_land_edge_corner_touch(make_data_dir, tmp_path):
    """Diagonally touching squares share no border: no land edge."""
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 10), square("B", 20, 20, 10)],
        include=["A", "B"],
        overrides=graph_overrides(sea_zones=_ONE_ZONE),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edges = edges_by_key(read_graph(out_dir))
    assert ("a", "b") not in edges


def test_coast_edge_length(make_data_dir, tmp_path):
    """One square inside a zone ring: coast len ~= perimeter."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6)],
        include=["Alpha"],
        overrides=graph_overrides(sea_zones=_ONE_ZONE),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("alpha", "sea_a")]
    assert edge["type"] == "coast"
    assert 22.0 < edge["len"] < 26.0  # ~24 perimeter


def test_sea_edge_two_zones_one_body(make_data_dir, tmp_path):
    """Squares 4 apart: bands merge, two seeds share the body -> sea edge."""
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10, 6), square("Beta", 20, 10, 6)],
        include=["Alpha", "Beta"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[28.0, 13.0]]},
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("sea_a", "sea_b")]
    assert edge["type"] == "sea"
    assert edge["len"] > 0  # computed contact length


def test_contact_below_min_no_edge(make_data_dir, tmp_path):
    """Niche capped by land: N's only water contact is a 0.25 sliver."""
    data_dir = make_data_dir(
        svg_elems=[
            _rect("L", 10, 10, 10, 10),
            _rect("R", 20.25, 10, 10, 10),
            _rect("N", 20, 19, 0.25, 1),
            _rect("M", 10, 20, 20.25, 6),
        ],
        include=["L", "R", "N", "M"],
        overrides=graph_overrides(sea_zones=_ONE_ZONE),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edges = edges_by_key(read_graph(out_dir))
    assert ("n", "sea_a") not in edges  # contact 0.25 < min_border_length
    # the neighbours do touch the zone normally
    assert ("l", "sea_a") in edges
    assert ("r", "sea_a") in edges


def test_bfs_tie_smaller_zone_index(make_data_dir, tmp_path):
    """Two seeds on one body: contested pixels go to the earlier zone."""
    mid_label, left_label = {}, {}
    for tag, zones in (
        ("ab", [{"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[28.0, 13.0]]}]),
        ("ba", [{"key": "sea_b", "name_ru": "B", "seeds": [[28.0, 13.0]]},
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]}]),
    ):
        data_dir = make_data_dir(
            svg_elems=[square("Alpha", 10, 10, 6), square("Beta", 20, 10, 6)],
            include=["Alpha", "Beta"],
            overrides=graph_overrides(sea_zones=zones),
        )
        out_dir = tmp_path / tag
        assert run_graph(data_dir, out_dir) == 0
        # contested middle pixel (equidistant from both seeds)...
        mid_label[tag] = label_at(out_dir, 18.0, 13.0)
        # ...and a pixel nearer the sea_a seed
        left_label[tag] = label_at(out_dir, 17.0, 13.0)
    assert mid_label["ab"] == 1  # sea_a is zone 1
    assert mid_label["ba"] == 1  # sea_b is zone 1
    assert left_label["ab"] == 1
    assert left_label["ba"] == 2  # sea_a is zone 2 here -> labels flipped


def test_edges_remove_automatic(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 10), _rect("B", 20, 10, 10, 5)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            edges_remove=[{"a": "a", "b": "b"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edges = edges_by_key(read_graph(out_dir))
    assert ("a", "b") not in edges


def test_edges_remove_not_found(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 30, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE + [
                {"key": "sea_b", "name_ru": "B", "seeds": [[37.0, 13.0]]}
            ],
            edges_remove=[{"a": "a", "b": "b"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "EDGE_REMOVE_NOT_FOUND" in capsys.readouterr().err


def test_edges_add_sea_between_bodies(make_data_dir, tmp_path):
    """Manual sea edge between zones of different water bodies: len null."""
    elems = _ring("Xa", 32, 32, cell=8) + _ring("Xb", 72, 32, cell=8)
    data_dir = make_data_dir(
        svg_elems=elems,
        include=_ring_keys("Xa") + _ring_keys("Xb"),
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_o", "name_ru": "O",
                 "seeds": [[21.0, 36.0], [91.0, 36.0]]},
                {"key": "sea_p", "name_ru": "P", "seeds": [[36.0, 36.0]]},
            ],
            edges_add=[{"a": "sea_o", "b": "sea_p", "type": "sea"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("sea_o", "sea_p")]
    assert edge["type"] == "sea"
    assert edge["len"] is None


def test_edges_add_duplicate_is_info(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 10), _rect("B", 20, 10, 10, 5)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            edges_add=[{"a": "a", "b": "b", "type": "land"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edges = edges_by_key(read_graph(out_dir))
    assert ("a", "b") in edges
    assert edges[("a", "b")]["len"] is not None  # kept the automatic edge
    report = (out_dir / "graph_report.md").read_text()
    assert "already present" in report


def test_edges_add_type_mismatch(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6)],
        include=["A"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            edges_add=[{"a": "a", "b": "sea_a", "type": "sea"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "EDGE_TYPE_MISMATCH" in capsys.readouterr().err


def test_edges_add_unknown_node(make_data_dir, tmp_path, capsys):
    """A well-formed land key that names no node (technical_excluded)."""
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 30, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            technical_exclude=["b"],
            edges_add=[{"a": "a", "b": "b", "type": "land"}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "EDGE_UNKNOWN_NODE" in capsys.readouterr().err


def test_strait_between_islands(make_data_dir, tmp_path):
    """Two islands across 1 unit of water share a strait."""
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 17, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            straits=[{"a": "a", "b": "b", "name": "Narrows",
                      "multiplier": 0.5}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("a", "b")]
    assert edge["type"] == "strait"
    assert edge["name"] == "Narrows"
    assert edge["multiplier"] == 0.5
    assert edge["len"] is None


def test_strait_already_connected(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 10), _rect("B", 20, 10, 10, 5)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            straits=[{"a": "a", "b": "b", "name": "S", "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "STRAIT_ALREADY_CONNECTED" in capsys.readouterr().err


def test_strait_sea_endpoint(make_data_dir, tmp_path, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6)],
        include=["A"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            straits=[{"a": "a", "b": "sea_a", "name": "S",
                      "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    assert "EDGE_TYPE_MISMATCH" in capsys.readouterr().err


def test_disconnected_island_in_seeded_pond(make_data_dir, tmp_path, capsys):
    """An island whose pond is a separate zone disconnects the graph."""
    elems = (
        _ring("X", 50, 30, cell=6)
        + [square("Main", 10, 10, 10), square("Isl", 50.5, 31.5, 3)]
    )
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Main", "Isl"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 15.0]]},
                {"key": "sea_p", "name_ru": "P", "seeds": [[51.0, 30.0]]},
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 1
    err = capsys.readouterr().err
    assert "GRAPH_DISCONNECTED" in err
    # the two components are {main, sea_a} and {isl, sea_p}
    assert "component of 2: " in err
    assert "sea_p" in err or "sea_a" in err


def test_disconnected_fixed_by_strait(make_data_dir, tmp_path):
    elems = (
        _ring("X", 50, 30, cell=6)
        + [square("Main", 10, 10, 10), square("Isl", 50.5, 31.5, 3)]
    )
    data_dir = make_data_dir(
        svg_elems=elems,
        include=["Main", "Isl"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 15.0]]},
                {"key": "sea_p", "name_ru": "P", "seeds": [[51.0, 30.0]]},
            ],
            straits=[{"a": "isl", "b": "main", "name": "Ferry",
                      "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    edge = edges_by_key(read_graph(out_dir))[("isl", "main")]
    assert edge["type"] == "strait"
    assert edge["name"] == "Ferry"
    # isl also coasts on its pond zone
    assert ("isl", "sea_p") in edges_by_key(read_graph(out_dir))
    report = (out_dir / "graph_report.md").read_text()
    assert "without straits and manual edges: NO" in report


def test_edge_pairs_normalised_and_unique(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 17, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[25.0, 13.0]]},
            ],
            straits=[{"a": "a", "b": "b", "name": "S", "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir) == 0
    graph = read_graph(out_dir)
    pairs = [(e["a"], e["b"]) for e in graph["edges"]]
    assert all(a < b for a, b in pairs)
    assert len(set(pairs)) == len(pairs)
    assert pairs == sorted(pairs)


def test_determinism(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 30, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[8.0, 13.0]]},
                {"key": "sea_b", "name_ru": "B", "seeds": [[38.0, 13.0]]},
            ],
            straits=[{"a": "a", "b": "b", "name": "S", "multiplier": None}],
        ),
    )
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    assert run_graph(data_dir, out1) == 0
    lock1 = (data_dir / "ids.lock.json").read_bytes()
    assert run_graph(data_dir, out2) == 0
    for name in ("graph.json", "graph_report.md", "sea_raster.json",
                 "land_nodes.json"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()
    assert np.array_equal(
        np.load(out1 / "sea_labels.npy"), np.load(out2 / "sea_labels.npy")
    )
    assert np.array_equal(
        np.load(out1 / "sea_kinds.npy"), np.load(out2 / "sea_kinds.npy")
    )
    assert (data_dir / "ids.lock.json").read_bytes() == lock1
    assert run_graph(data_dir, tmp_path / "out3", check=True) == 0


def test_preview_written(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("A", 10, 10, 6), square("B", 17, 10, 6)],
        include=["A", "B"],
        overrides=graph_overrides(
            sea_zones=_ONE_ZONE,
            straits=[{"a": "a", "b": "b", "name": "S", "multiplier": None}],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_graph(data_dir, out_dir, preview=True) == 0
    png = out_dir / "graph_preview.png"
    assert png.exists()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    with Image.open(png) as img:
        # frame 21x14 units * 6 ppu
        assert img.size == (126, 84)
