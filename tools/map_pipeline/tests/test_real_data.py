"""End-to-end run on the committed real map inputs.

Skipped when ``data/map/source/map.svg`` is absent (e.g. partial checkout).
The source file is verified by size and SHA-256 before use.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import pytest
import yaml

from conftest import run_graph, run_nodes

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "map"
SOURCE = DATA_DIR / "source" / "map.svg"

EXPECTED_SIZE = 6_601_107
EXPECTED_SHA256 = (
    "918bc3fc078331c9ab2204433e35767908ff66e83978b988d389a5c70c2b6f13"
)

pytestmark = pytest.mark.real_data


@pytest.fixture(scope="module")
def real_data_dir(tmp_path_factory):
    """A full copy of data/map the pipeline may write into."""
    if not SOURCE.exists():
        pytest.skip("data/map/source/map.svg is absent")
    blob = SOURCE.read_bytes()
    assert len(blob) == EXPECTED_SIZE
    assert hashlib.sha256(blob).hexdigest() == EXPECTED_SHA256

    dst = tmp_path_factory.mktemp("real_data") / "map"
    (dst / "source").mkdir(parents=True)
    shutil.copy2(SOURCE, dst / "source" / "map.svg")
    for name in ("boundary.yaml", "overrides.yaml", "ids.lock.json"):
        src = DATA_DIR / name
        if src.exists():
            shutil.copy2(src, dst / name)
    return dst


def test_real_nodes(real_data_dir, tmp_path):
    out_dir = tmp_path / "out"
    t0 = time.time()
    assert run_nodes(real_data_dir, out_dir) == 0
    print(f"\nreal-data nodes run: {time.time() - t0:.1f}s")

    nodes = json.loads((out_dir / "land_nodes.json").read_text())
    assert len(nodes) == 1086
    assert [n["id"] for n in nodes] == list(range(1001, 2087))
    assert all(n["parts"] >= 1 for n in nodes)

    # the lock also holds the 37 sea zone ids (2087..2123)
    lock = json.loads((real_data_dir / "ids.lock.json").read_text())
    assert len(lock["ids"]) == 1086 + 37
    sea_ids = sorted(v for k, v in lock["ids"].items() if k.startswith("sea_"))
    assert sea_ids == list(range(2087, 2124))
    assert lock["ids"]["sea_adriatic"] == 2087

    # second run changes nothing; --check agrees
    before = (real_data_dir / "ids.lock.json").read_bytes()
    nodes_bytes = (out_dir / "land_nodes.json").read_bytes()
    assert run_nodes(real_data_dir, out_dir) == 0
    assert (real_data_dir / "ids.lock.json").read_bytes() == before
    assert (out_dir / "land_nodes.json").read_bytes() == nodes_bytes
    assert run_nodes(real_data_dir, out_dir, check=True) == 0


def test_real_isolated_parts(real_data_dir, tmp_path, capsys):
    """Without drop_parts the three known detached parts must fail."""
    ov_path = real_data_dir / "overrides.yaml"
    doc = yaml.safe_load(ov_path.read_text(encoding="utf-8"))
    doc["drop_parts"] = []
    ov_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    try:
        out_dir = tmp_path / "out_empty_drops"
        assert run_nodes(real_data_dir, out_dir) == 1
    finally:
        shutil.copy2(DATA_DIR / "overrides.yaml", ov_path)

    err = capsys.readouterr().err
    blocks = [ln for ln in err.splitlines() if ln.startswith("ISOLATED_PART:")]
    assert len(blocks) == 3

    pattern = re.compile(
        r"key=(\S+) point=\(([-\d.]+), ([-\d.]+)\) area=([-\d.]+)"
    )
    found = []
    for line in blocks:
        m = pattern.search(line)
        assert m, line
        found.append(
            (m.group(1), float(m.group(2)), float(m.group(3)),
             float(m.group(4)))
        )

    expected = [
        ("kemi_lappmark", 643.6, 32.9, 6.91),
        ("nordland", 614.7, 39.3, 4.08),
        ("nordland", 616.6, 40.9, 0.04),
    ]
    for (key, x, y, area), (ekey, ex, ey, earea) in zip(
        sorted(found), sorted(expected)
    ):
        assert key == ekey
        assert abs(x - ex) < 0.1
        assert abs(y - ey) < 0.1
        assert abs(area - earea) < 0.01


def test_real_graph(real_data_dir, tmp_path, capsys):
    """Steps 1-6 on the real map: nodes, edges, zones, invariants.

    Numbers are sanity bands from the Lead AI's independent prototype, not
    exact values; the sea sizes are printed for review either way.
    """
    out_dir = tmp_path / "out_graph"
    t0 = time.time()
    assert run_graph(real_data_dir, out_dir, preview=True) == 0
    print(f"\nreal-data graph run: {time.time() - t0:.1f}s")

    graph = json.loads(
        (out_dir / "graph.json").read_text(encoding="utf-8")
    )
    land = [n for n in graph["nodes"] if n["kind"] == "LAND"]
    seas = [n for n in graph["nodes"] if n["kind"] == "SEA"]
    assert len(land) == 1086
    assert len(seas) == 37
    assert [n["id"] for n in land] == list(range(1001, 2087))
    assert [n["id"] for n in seas] == list(range(2087, 2124))
    assert seas[0]["key"] == "sea_adriatic"

    for n in seas:
        print(f"  {n['key']}: {n['area']}")
    by_key = {n["key"]: n for n in seas}
    assert 5.0 < by_key["sea_marmara"]["area"] < 40.0
    for n in seas:
        if n["key"] != "sea_marmara":
            assert n["area"] > 40.0, n["key"]
    assert 55.0 <= by_key["sea_azov"]["area"] <= 72.0
    assert 355.0 <= by_key["sea_black_east"]["area"] <= 380.0
    assert abs(by_key["sea_danish_straits"]["area"] - 73.0) < 20.0

    edges = graph["edges"]
    by_type = {}
    for e in edges:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print("  edge counts:", by_type)
    assert 2700 <= by_type["land"] <= 2850
    assert 380 <= by_type["coast"] <= 420
    auto_sea = [e for e in edges
                if e["type"] == "sea" and e["len"] is not None]
    manual_sea = [e for e in edges
                  if e["type"] == "sea" and e["len"] is None]
    assert 38 <= len(auto_sea) <= 50
    # 4 manual sea edges are listed in overrides. The second sea_black_east
    # seed anchors the azov border at the Kerch strait: either the raster no
    # longer connects the two zones and the edges_add entry is the only link
    # (4 manual edges), or a residual contact < 1.5 remains automatic plus an
    # INFO line (3 manual edges).
    assert len(manual_sea) in (3, 4)
    assert by_type["strait"] == 16
    by_id = {n["id"]: n["key"] for n in graph["nodes"]}
    pairs = {(by_id[e["a"]], by_id[e["b"]]): e for e in edges}
    for a, b in (
        ("sea_atl_iberia", "sea_alboran"),
        ("sea_marmara", "sea_black_west"),
        ("sea_marmara", "sea_aegean"),
        ("sea_azov", "sea_black_east"),
    ):
        pair = tuple(sorted((a, b)))
        assert pairs[pair]["type"] == "sea", pair
    # Kerch: manual edge (len None) or residual automatic contact < 1.5
    kerch = pairs[tuple(sorted(("sea_azov", "sea_black_east")))]
    assert kerch["len"] is None or kerch["len"] < 1.5

    deg = {n["id"]: 0 for n in graph["nodes"]}
    for e in edges:
        deg[e["a"]] += 1
        deg[e["b"]] += 1
    assert all(deg[n["id"]] > 0 for n in land)
    assert all(deg[n["id"]] <= 20 for n in land)

    report = (out_dir / "graph_report.md").read_text(encoding="utf-8")
    wo_section = report.split("## water_outside")[1].split("##")[0]
    wo_lines = [ln for ln in wo_section.splitlines()
                if "component area" in ln]
    assert len(wo_lines) == 3  # Aral, Red Sea, Persian Gulf
    assert "without straits and manual edges: yes" in report

    # raster contract for MP-3
    import numpy as np

    meta = json.loads(
        (out_dir / "sea_raster.json").read_text(encoding="utf-8")
    )
    labels = np.load(out_dir / "sea_labels.npy")
    kinds = np.load(out_dir / "sea_kinds.npy")
    assert labels.dtype == np.int16
    assert kinds.dtype == np.uint8
    assert meta["width"] == labels.shape[1]
    assert meta["height"] == labels.shape[0]
    assert len(meta["zone_keys"]) == 37
    assert labels.max() == 37  # every zone got pixels
    assert (out_dir / "graph_preview.png").exists()

    # second run is byte-identical; --check passes against the committed lock
    snapshot = {
        p.name: p.read_bytes()
        for p in out_dir.iterdir()
        if p.suffix in {".json", ".md"}
    }
    labels_b = np.load(out_dir / "sea_labels.npy").copy()
    kinds_b = np.load(out_dir / "sea_kinds.npy").copy()
    assert run_graph(real_data_dir, out_dir) == 0
    for name, blob in snapshot.items():
        assert (out_dir / name).read_bytes() == blob, name
    assert np.array_equal(np.load(out_dir / "sea_labels.npy"), labels_b)
    assert np.array_equal(np.load(out_dir / "sea_kinds.npy"), kinds_b)
    assert run_graph(real_data_dir, out_dir, check=True) == 0
