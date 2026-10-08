"""
Real-data guard: load the committed ``data/map/`` with the real
``configs/01_map.yaml`` — no mocks, the same path the server startup
(Issue 3) will take.

Skipped only when ``data/map/manifest.json`` is absent (e.g. a partial
checkout); when the files exist this test must run green.
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest

from modules._01_map.config_schema import MapConfig
from modules._01_map.loader import load_map_data
from modules._01_map.service import (
    MapService,
    NodeNotLandError,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data" / "map"

pytestmark = pytest.mark.skipif(
    not (DATA_DIR / "manifest.json").exists(),
    reason="data/map/manifest.json absent — map data not committed",
)


@pytest.fixture(scope="module")
def real_service() -> MapService:
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    tracemalloc.start()
    t0 = time.perf_counter()
    data = load_map_data(DATA_DIR, config)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"\nreal map load: {elapsed:.2f}s, "
        f"peak tracemalloc {peak / 1e6:.1f} MB"
    )
    assert elapsed < 30.0, f"map load took {elapsed:.1f}s"
    return MapService(data, config)


def test_real_map_sanity(real_service):
    data = real_service.map_data
    manifest = data.manifest

    # map2_2 split: 1066 active nodes; the 58 retired ids stay in the lock.
    assert len(data.nodes) == len(manifest.nodes) == 1066
    assert len(data.retired_ids) == 58
    kinds = {n.kind for n in data.nodes.values()}
    assert kinds == {"LAND", "SEA"}
    assert len(data.edges) == len(manifest.edges) == 3062

    # graph connectivity is already enforced by the loader (INV-M3);
    # degrees stay under the config limit (checked at load time too)
    max_deg = max(len(v) for v in data.adjacency.values())
    config_max = 60  # limits.max_edges_per_node in configs/01_map.yaml
    assert max_deg <= config_max
    print(f"  max node degree: {max_deg} (limit {config_max})")

    # strait multiplier: the Dover strait carries an explicit value or
    # falls back to the config default — either way inside [0.05, 1.0]
    straits = [e for e in data.edges.values() if e.type == "strait"]
    assert len(straits) == 16
    for e in straits:
        mult = real_service.strait_multiplier(e.a, e.b)
        assert mult is not None and 0.05 <= mult <= 1.0


def test_real_group_and_path_plausible(real_service):
    data = real_service.map_data

    # two known LAND provinces joined by a land edge
    land_edge = next(
        e for e in data.edges.values() if e.type == "land"
    )
    a, b = land_edge.a, land_edge.b
    assert real_service.is_group_connected([a, b])
    assert real_service.is_group_connected([a])

    # a land pair separated by a strait is a connected starting group
    strait = next(
        e for e in data.edges.values() if e.type == "strait"
    )
    assert real_service.is_group_connected([strait.a, strait.b])

    # a land node and a sea zone can never form a legal group
    sea = next(n for n in data.nodes.values() if n.kind == "SEA")
    with pytest.raises(NodeNotLandError):
        real_service.is_group_connected([a, sea.id])

    # shortest path between the strait endpoints exists and is sane
    res = real_service.shortest_path(strait.a, strait.b, lambda e: 1.0)
    assert res is not None
    assert res.nodes[0] == strait.a and res.nodes[-1] == strait.b
    assert res.total_cost == len(res.nodes) - 1 >= 1.0

    # a path across the map between two distant nodes
    first, last = 1001, 2123
    res = real_service.shortest_path(first, last, lambda e: 1.0)
    assert res is not None
    assert res.nodes[0] == first and res.nodes[-1] == last
    print(
        f"  path 1001 -> 2123: {len(res.nodes)} nodes, "
        f"cost {res.total_cost}"
    )
