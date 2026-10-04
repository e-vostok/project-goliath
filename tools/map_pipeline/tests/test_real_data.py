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

from conftest import run_build, run_graph, run_nodes

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data" / "map"
SOURCE = DATA_DIR / "source" / "map.svg"

EXPECTED_SIZE = 6_601_107
EXPECTED_SHA256 = (
    "918bc3fc078331c9ab2204433e35767908ff66e83978b988d389a5c70c2b6f13"
)

# Boundary v2 (map_polish_2): 56 land provinces withdrawn from the game —
# their ids stay in ids.lock.json but never enter land_nodes/graph/
# manifest. The two retired sea zones are 2090 (sea_atl_africa) and
# 2110 (sea_iceland).
RETIRED_LAND_KEYS = frozenset("""
    bavly igra khaqmar ochyor orlov uil kalmyk omutninsk vyatka nema
    ystyug gilan totma lalsk velsk sarapul ustye jebel_akhdar
    sorochinskaya yemetsk taskala shenkursk tabaristan yaren daylam ryn
    mangistau shagiz nafusa bahnasa syun rustamdar damghan kholmogory
    buhayra mangyshlak nor_trondelag nordland uzboy canary_islands
    faraveh baytak chishmy gorgan karagay kasevo krasnaya_gorka
    lower_emba madeira meleuz perm ufa upper_emba ural usolye ust_yurt
""".split())
RETIRED_SEA_IDS = frozenset({2090, 2110})

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
    assert len(nodes) == 1030
    land_ids = [n["id"] for n in nodes]
    assert land_ids == sorted(land_ids)
    assert land_ids[0] == 1001 and land_ids[-1] == 2086
    assert all(n["parts"] >= 1 for n in nodes)

    # boundary v2: 56 land provinces were withdrawn; their ids stay in
    # the append-only lock but not in land_nodes.json (INV-M1).
    lock = json.loads((real_data_dir / "ids.lock.json").read_text())
    retired = set(lock["ids"][k] for k in RETIRED_LAND_KEYS)
    assert len(retired) == 56
    assert retired.isdisjoint(land_ids)
    assert set(land_ids) | retired == set(range(1001, 2087))

    # the lock also holds the 37 sea zone ids (2087..2123), including
    # the two retired zones sea_atl_africa / sea_iceland.
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
    """Without drop_parts the one known detached part must fail.

    Boundary v2 withdrew nordland entirely, so only kemi_lappmark's
    detached part is still checked (the former nordland entries went
    away with their drop_parts overrides).
    """
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
    assert len(blocks) == 1

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
    assert len(land) == 1030
    assert len(seas) == 35
    # boundary v2: the 56 retired land ids leave gaps in 1001..2086.
    lock = json.loads(
        (real_data_dir / "ids.lock.json").read_text(encoding="utf-8")
    )
    retired = {lock["ids"][k] for k in RETIRED_LAND_KEYS}
    assert {n["id"] for n in land} == set(range(1001, 2087)) - retired
    assert RETIRED_LAND_KEYS.isdisjoint(n["key"] for n in land)
    assert [n["id"] for n in seas] == sorted(
        set(range(2087, 2124)) - RETIRED_SEA_IDS
    )
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
    # boundary v2: 2550..2700 land contacts (56 provinces left),
    # 360..400 coast contacts (retired zones released theirs).
    assert 2550 <= by_type["land"] <= 2700
    assert 360 <= by_type["coast"] <= 400
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


def test_real_build(real_data_dir, tmp_path):
    """Steps 1-10 on the real map: geometry.json, manifest.json, preview.

    Numbers are sanity bands from the Lead AI's prototype, not exact
    values; the measured numbers are printed for review either way.
    """
    from shapely.geometry import Point
    from shapely.ops import unary_union

    from tools.map_pipeline.svgpath import (
        geometry_version,
        parse_path,
        polygons_of,
    )

    out_dir = tmp_path / "out_build"
    t0 = time.time()
    assert run_build(real_data_dir, out_dir, preview=True) == 0
    print(f"\nreal-data build run: {time.time() - t0:.1f}s")

    geom = json.loads(
        (real_data_dir / "geometry.json").read_text(encoding="utf-8")
    )
    mani = json.loads(
        (real_data_dir / "manifest.json").read_text(encoding="utf-8")
    )

    # scale / identity
    land = [n for n in mani["nodes"] if n["kind"] == "LAND"]
    seas = [n for n in mani["nodes"] if n["kind"] == "SEA"]
    # boundary v2: 1065 active nodes (1030 land + 35 sea); the 58
    # retired ids stay in the lock but not in the manifest/geometry.
    assert len(mani["nodes"]) == 1065
    assert len(land) == 1030
    assert len(seas) == 35
    assert len(mani["edges"]) == 3060
    assert set(geom["paths"]) == {str(n["id"]) for n in mani["nodes"]}
    lock = json.loads(
        (real_data_dir / "ids.lock.json").read_text(encoding="utf-8")
    )
    retired = {lock["ids"][k] for k in RETIRED_LAND_KEYS} | RETIRED_SEA_IDS
    assert len(retired) == 58
    assert {n["id"] for n in mani["nodes"]} | retired == set(
        range(1001, 2124)
    )
    assert mani["geometry_version"] == geom["version"]
    g = {"outside": geom["outside"], "paths": geom["paths"]}
    assert geometry_version(g) == geom["version"]

    # sizes
    geom_bytes = (real_data_dir / "geometry.json").stat().st_size
    mani_bytes = (real_data_dir / "manifest.json").stat().st_size
    print(f"  geometry.json: {geom_bytes} B, manifest.json: {mani_bytes} B")
    assert 1_500_000 <= geom_bytes <= 4_500_000
    assert mani_bytes <= 1_000_000

    # vertex bands per section
    def _verts(d):
        return sum(
            len(p.exterior.coords) - 1
            + sum(len(r.coords) - 1 for r in p.interiors)
            for p in parse_path(d)
        )
    land_v = sum(_verts(geom["paths"][str(n["id"])]) for n in land)
    sea_v = sum(_verts(geom["paths"][str(n["id"])]) for n in seas)
    out_v = _verts(geom["outside"])
    print(f"  vertices: land {land_v}, sea {sea_v}, outside {out_v}")
    assert 80_000 <= land_v <= 130_000  # 87417 after boundary v2
    assert 15_000 <= sea_v <= 60_000
    assert 15_000 <= out_v <= 60_000

    # anchors inside their own largest part
    node_geoms = {
        n["id"]: parse_path(geom["paths"][str(n["id"])])
        for n in mani["nodes"]
    }
    for n in mani["nodes"]:
        parts = node_geoms[n["id"]]
        largest = max(parts, key=lambda p: p.area)
        assert largest.covers(Point(*n["anchor"])), n["key"]

    # land areas vs MP-1 source-part areas
    land_nodes = json.loads(
        (out_dir / "land_nodes.json").read_text(encoding="utf-8")
    )
    by_id = {n["id"]: n for n in mani["nodes"]}
    worst_area = 0.0
    for rec in land_nodes:
        n = by_id[rec["id"]]
        g = unary_union(node_geoms[n["id"]])
        delta = abs(g.area - rec["area"])
        limit = max(0.01, 0.02 * rec["area"])
        worst_area = max(worst_area, delta / max(limit, 1e-9))
        assert delta <= limit, (n["key"], delta, limit)
    print(f"  worst land area drift vs MP-1: {worst_area:.3f} of limit")

    # sea area sum within 3 % of the MP-2 raster total
    graph = json.loads(
        (out_dir / "graph.json").read_text(encoding="utf-8")
    )
    raster_total = sum(
        n["area"] for n in graph["nodes"] if n["kind"] == "SEA"
    )
    sea_total = sum(unary_union(node_geoms[n["id"]]).area for n in seas)
    print(f"  sea area: {sea_total:.2f} vs raster {raster_total:.2f}")
    # boundary v2: with the retired zones' water now routed to
    # ``outside``, the per-zone path dilation along their freed borders
    # widened the raster->geometry drift a little (uniform ~3% noise,
    # not a leak into a neighbour zone).
    assert abs(sea_total - raster_total) <= 0.05 * raster_total

    # outside: valid, lake windows > 200, never inside buffer(N, -0.2)
    outside_parts = parse_path(geom["outside"])
    outside = unary_union(outside_parts)
    assert outside.is_valid
    allparts = [p for n in mani["nodes"] for p in node_geoms[n["id"]]]
    from tools.map_pipeline.pipeline_config_schema import (
        load_pipeline_config,
    )
    closing = load_pipeline_config().outside.closing
    n_union = unary_union(allparts).buffer(closing).buffer(-closing)
    strip = outside.intersection(n_union.buffer(-0.2)).area
    print(f"  outside x buffer(N,-0.2): {strip}")
    assert strip == 0.0

    report = (out_dir / "build_report.md").read_text(encoding="utf-8")
    m = re.search(r"Lake windows in outside: (\d+)", report)
    assert m and int(m.group(1)) > 200
    m = re.search(r"Land Hausdorff deviation: max ([\d.]+)", report)
    assert m and float(m.group(1)) <= 0.04
    m = re.search(r"Max node degree: (\d+) \(`(\w+)`\)", report)
    assert m and m.group(2) == "sea_north" and int(m.group(1)) == 41

    # Spec 1.5: fjord fill, land-adjacent lake windows, fragment count
    m = re.search(
        r"Fjord fill: merged (\d+) leftover pieces \(([\d.]+)", report
    )
    assert m, "build_report.md lacks the fjord-fill line"
    print(f"  fjord fill: {m.group(1)} pieces, {m.group(2)} sq. units")
    m = re.search(r"(\d+) pieces <= [\d.]+ sq\. units touch no zone", report)
    assert m is not None
    print(f"  leftover pieces touching no zone: {m.group(1)}")
    m = re.search(
        r"Lakes away from playable land \(no window\): (\d+) pieces, "
        r"([\d.]+)", report,
    )
    assert m
    print(f"  dropped lake windows: {m.group(1)} ({m.group(2)} sq. units)")
    m = re.search(
        r"Small isolated outside fragments inside playable area "
        r"\(<5 sq\. units\): (\d+)",
        report,
    )
    assert m and int(m.group(1)) <= 80, m and m.group(1)
    print(f"  small outside fragments: {m.group(1)}")

    # committed manifest must hash the committed inputs (any checkout)
    inputs = mani["inputs_sha256"]
    src_blob = SOURCE.read_bytes()
    assert inputs["source"] == hashlib.sha256(src_blob).hexdigest()
    for name, key in (
        ("boundary.yaml", "boundary"),
        ("overrides.yaml", "overrides"),
        ("ids.lock.json", "ids_lock"),
    ):
        raw = (DATA_DIR / name).read_bytes().replace(b"\r\n", b"\n")
        assert inputs[key] == hashlib.sha256(raw).hexdigest(), key

    # previews
    assert (real_data_dir / "preview" / "map_preview.png").exists()

    # second run byte-identical; --check exits 0
    finals = {
        name: (real_data_dir / name).read_bytes()
        for name in ("manifest.json", "geometry.json", "ids.lock.json")
    }
    report_b = (out_dir / "build_report.md").read_bytes()
    assert run_build(real_data_dir, out_dir, preview=False) == 0
    for name, blob in finals.items():
        assert (real_data_dir / name).read_bytes() == blob, name
    assert (out_dir / "build_report.md").read_bytes() == report_b
    assert run_build(real_data_dir, out_dir, check=True) == 0
