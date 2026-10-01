"""ids.lock.json append-only behaviour (INV-M1) and --check mode."""
from __future__ import annotations

import json

from conftest import run_nodes, square


def test_first_run_assigns_from_1001_in_key_order(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[
            square("Beta", 30, 10),
            square("Alpha", 10, 10),
            square("Gamma", 50, 10),
        ],
        include=["Beta", "Alpha", "Gamma"],
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    lock = json.loads((data_dir / "ids.lock.json").read_text())
    assert lock == {
        "version": 1,
        "ids": {"alpha": 1001, "beta": 1002, "gamma": 1003},
    }


def test_rerun_and_check(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10), square("Beta", 30, 10)],
        include=["Alpha", "Beta"],
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0
    lock_bytes = (data_dir / "ids.lock.json").read_bytes()
    nodes_bytes = (out_dir / "land_nodes.json").read_bytes()

    assert run_nodes(data_dir, out_dir) == 0
    assert (data_dir / "ids.lock.json").read_bytes() == lock_bytes
    assert (out_dir / "land_nodes.json").read_bytes() == nodes_bytes

    # --check: nothing changes -> 0, and writes nothing new.
    assert run_nodes(data_dir, out_dir, check=True) == 0


def test_check_fails_when_lock_would_change(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10)], include=["Alpha"]
    )
    out_dir = tmp_path / "out"
    # no lock yet -> --check exits 1 and writes nothing
    assert run_nodes(data_dir, out_dir, check=True) == 1
    assert not (data_dir / "ids.lock.json").exists()
    assert not (out_dir / "land_nodes.json").exists()


def test_new_key_gets_next_id(make_data_dir, tmp_path):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10), square("Beta", 30, 10)],
        include=["Alpha", "Beta"],
    )
    out_dir = tmp_path / "out"
    assert run_nodes(data_dir, out_dir) == 0

    # add a province to the same data dir
    from conftest import svg_document, base_overrides
    import yaml

    (data_dir / "source" / "map.svg").write_text(
        svg_document(
            [square("Alpha", 10, 10), square("Beta", 30, 10),
             square("Zeta", 50, 10)]
        ),
        encoding="utf-8",
    )
    (data_dir / "boundary.yaml").write_text(
        yaml.safe_dump(
            {"include": ["Alpha", "Beta", "Zeta"], "exclude_explicit": []}
        ),
        encoding="utf-8",
    )
    assert run_nodes(data_dir, out_dir) == 0
    lock = json.loads((data_dir / "ids.lock.json").read_text())
    assert lock["ids"]["alpha"] == 1001
    assert lock["ids"]["beta"] == 1002
    assert lock["ids"]["zeta"] == 1003


def test_removed_key_is_error(make_data_dir, run_pipeline, capsys):
    data_dir = make_data_dir(
        svg_elems=[square("Alpha", 10, 10), square("Beta", 30, 10)],
        include=["Alpha", "Beta"],
    )
    code, out_dir = run_pipeline(data_dir)
    assert code == 0
    # remove Beta from boundary and svg
    import yaml
    from conftest import svg_document

    (data_dir / "source" / "map.svg").write_text(
        svg_document([square("Alpha", 10, 10)]), encoding="utf-8"
    )
    (data_dir / "boundary.yaml").write_text(
        yaml.safe_dump({"include": ["Alpha"], "exclude_explicit": []}),
        encoding="utf-8",
    )
    code, _ = run_pipeline(data_dir)
    assert code == 1
    assert "KEY_REMOVED" in capsys.readouterr().err


def test_corrupt_lock(make_data_dir, run_pipeline, capsys):
    for bad_lock in (
        {"version": 1, "ids": {"alpha": 1001, "beta": 1001}},  # dup id
        {"version": 1, "ids": {"Alpha": 1001}},               # bad key
        {"version": 1, "ids": {"alpha": 500}},                # id < 1001
        {"version": 2, "ids": {"alpha": 1001}},               # bad version
    ):
        data_dir = make_data_dir(
            svg_elems=[square("Alpha", 10, 10)],
            include=["Alpha"],
            lock=bad_lock,
        )
        code, _ = run_pipeline(data_dir)
        assert code == 1
        assert "IDS_LOCK_INVALID" in capsys.readouterr().err
