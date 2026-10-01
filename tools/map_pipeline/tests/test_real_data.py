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

from conftest import run_nodes

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
