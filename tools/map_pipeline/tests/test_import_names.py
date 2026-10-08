"""map2_3 Phase B: import_names merges the filled table into names_ru."""
from __future__ import annotations

import json

import pytest
import yaml
from openpyxl import Workbook

from conftest import base_overrides, run_build, square
from tools.map_pipeline.export_names import HEADERS, LAND_SHEET
from tools.map_pipeline.import_names import main


def _row(node_id, key, name):
    row = [None] * len(HEADERS)
    row[HEADERS.index("id")] = node_id
    row[HEADERS.index("key")] = key
    row[HEADERS.index("name_ru_new")] = name
    return row


def _table(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = LAND_SHEET
    ws.append(list(HEADERS))
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def _manifest_names(data_dir):
    doc = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    return {n["key"]: n["name_ru"] for n in doc["nodes"]}


def _names_ru(data_dir):
    doc = yaml.safe_load(
        (data_dir / "overrides.yaml").read_text(encoding="utf-8")
    )
    return doc["names_ru"]


@pytest.fixture
def built_dir(make_data_dir, tmp_path):
    """A built two-province mini map; returns (data_dir, out_dir)."""
    data_dir = make_data_dir(
        [square("Alpha", 10, 10, 12), square("Beta", 30, 10, 12)],
        include=["Alpha", "Beta"],
        overrides=base_overrides(
            sea_margin=30.0,
            sea_zones=[
                {"key": "sea_a", "name_ru": "A", "seeds": [[24.0, 16.0]]}
            ],
        ),
    )
    out_dir = tmp_path / "out"
    assert run_build(data_dir, out_dir) == 0
    return data_dir, out_dir


def _ids(data_dir):
    doc = json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )
    return {n["key"]: n["id"] for n in doc["nodes"]}


def _run(tmp_path, data_dir, out_dir, rows):
    table = _table(tmp_path / "names.xlsx", rows)
    return main(
        [str(table), "--data-dir", str(data_dir), "--out-dir", str(out_dir)]
    )


def test_import_writes_names_ru(built_dir, tmp_path):
    """Filled rows land in overrides.yaml and the regenerated manifest;
    geometry and ids.lock stay byte-identical (names are not geometry)."""
    data_dir, out_dir = built_dir
    ids = _ids(data_dir)
    geom_before = (data_dir / "geometry.json").read_bytes()
    lock_before = (data_dir / "ids.lock.json").read_bytes()

    rc = _run(
        tmp_path,
        data_dir,
        out_dir,
        [
            _row(ids["alpha"], "alpha", "Альфа"),
            _row(ids["beta"], "beta", "Бета-Земля"),
            _row(ids["alpha"], "alpha", None),  # empty cell: row skipped
        ],
    )

    assert rc == 0
    assert _names_ru(data_dir) == {
        "alpha": "Альфа",
        "beta": "Бета-Земля",
    }
    names = _manifest_names(data_dir)
    assert names["alpha"] == "Альфа"
    assert names["beta"] == "Бета-Земля"
    assert (data_dir / "geometry.json").read_bytes() == geom_before
    assert (data_dir / "ids.lock.json").read_bytes() == lock_before


def test_rejects_unknown_key(built_dir, tmp_path, capsys):
    """A used row whose key is no manifest LAND node aborts the import
    and is listed — nothing is written."""
    data_dir, out_dir = built_dir
    ids = _ids(data_dir)

    rc = _run(
        tmp_path,
        data_dir,
        out_dir,
        [
            _row(ids["alpha"], "alpha", "Альфа"),
            _row(9999, "not_a_node", "ZZZ"),
        ],
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "not_a_node" in err
    assert "row" in err.lower()
    assert _names_ru(data_dir) == {}


def test_reports_latin_name(built_dir, tmp_path, capsys):
    """Latin letters are a warning, not an error: the name is imported
    and the run reports it."""
    data_dir, out_dir = built_dir
    ids = _ids(data_dir)

    rc = _run(
        tmp_path,
        data_dir,
        out_dir,
        [_row(ids["alpha"], "alpha", "Moskva")],
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "latin_or_digits" in out
    assert "Moskva" in out
    assert _names_ru(data_dir) == {"alpha": "Moskva"}
