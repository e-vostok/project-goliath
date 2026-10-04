"""Shared helpers: real files in tmp_path, real pipeline — no mocks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.map_pipeline.__main__ import main


def square(name: str, x: float, y: float, size: float = 5.0) -> str:
    return (
        f'<path id="{name}" d="M {x} {y} h {size} v {size} h {-size} z"/>'
    )


def multi_square(name: str, rects: list[tuple[float, float, float]]) -> str:
    d = " ".join(f"M {x} {y} h {s} v {s} h {-s} z" for x, y, s in rects)
    return f'<path id="{name}" d="{d}"/>'


def svg_document(path_elems: list[str], defs_elems: list[str] | None = None) -> str:
    defs = f"<defs>{''.join(defs_elems or [])}</defs>"
    body = "".join(path_elems)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 680">'
        f"{defs}<svg id=\"map\">{body}</svg></svg>"
    )


def base_overrides(**kw) -> dict:
    data = dict(
        sea_margin=30.0,
        sea_margin_shape="square",
        sea_margin_smooth=10.0,
        lake_max_area=70.0,
        sea_like_water=[],
        lake_force=[],
        sea_link_gap=0.6,
        drop_parts=[],
        keep_parts=[],
        sea_zones=[],
        edges_add=[],
        edges_remove=[],
        straits=[],
        water_outside=[],
        technical_exclude=[],
        names_ru={},
    )
    data.update(kw)
    return data


@pytest.fixture
def make_data_dir(tmp_path):
    """Write a complete data dir; returns the directory Path.

    Each call gets its own subdirectory so several variants can coexist.
    """
    counter = {"n": 0}

    def _make(
        svg_elems: list[str],
        include: list[str],
        defs_elems: list[str] | None = None,
        exclude: list[str] | None = None,
        overrides: dict | None = None,
        lock: dict | None = None,
    ) -> Path:
        counter["n"] += 1
        data_dir = tmp_path / f"map{counter['n']}"
        (data_dir / "source").mkdir(parents=True)
        (data_dir / "source" / "map.svg").write_text(
            svg_document(svg_elems, defs_elems), encoding="utf-8"
        )
        (data_dir / "boundary.yaml").write_text(
            yaml.safe_dump(
                {"include": include, "exclude_explicit": exclude or []}
            ),
            encoding="utf-8",
        )
        (data_dir / "overrides.yaml").write_text(
            yaml.safe_dump(overrides if overrides is not None else base_overrides()),
            encoding="utf-8",
        )
        if lock is not None:
            (data_dir / "ids.lock.json").write_text(
                json.dumps(lock), encoding="utf-8"
            )
        return data_dir

    return _make


def run_nodes(data_dir: Path, out_dir: Path, check: bool = False) -> int:
    argv = ["nodes", "--data-dir", str(data_dir), "--out-dir", str(out_dir)]
    if check:
        argv.append("--check")
    return main(argv)


def run_graph(
    data_dir: Path,
    out_dir: Path,
    check: bool = False,
    preview: bool = False,
) -> int:
    argv = ["graph", "--data-dir", str(data_dir), "--out-dir", str(out_dir)]
    if check:
        argv.append("--check")
    if not preview:
        argv.append("--no-preview")
    return main(argv)


def run_build(
    data_dir: Path,
    out_dir: Path,
    check: bool = False,
    preview: bool = False,
    crops: list[str] | None = None,
) -> int:
    argv = ["build", "--data-dir", str(data_dir), "--out-dir", str(out_dir)]
    if check:
        argv.append("--check")
    if not preview:
        argv.append("--no-preview")
    if crops:
        argv += ["--crop"] + list(crops)
    return main(argv)


@pytest.fixture
def run_pipeline(tmp_path):
    def _run(data_dir: Path, check: bool = False) -> tuple[int, Path]:
        out_dir = tmp_path / "out"
        return run_nodes(data_dir, out_dir, check), out_dir

    return _run


@pytest.fixture
def run_graph_pipeline(tmp_path):
    def _run(
        data_dir: Path, check: bool = False, preview: bool = False
    ) -> tuple[int, Path]:
        out_dir = tmp_path / "out"
        return run_graph(data_dir, out_dir, check, preview), out_dir

    return _run


def sea_raster_meta(out_dir: Path) -> dict:
    return json.loads((out_dir / "sea_raster.json").read_text(encoding="utf-8"))


def kind_at(out_dir: Path, x: float, y: float) -> int:
    """Per-pixel water kind at a source point (see sea_raster.json)."""
    import numpy as np

    kinds = np.load(out_dir / "sea_kinds.npy")
    meta = sea_raster_meta(out_dir)
    x0, y0, r = meta["frame"][0], meta["frame"][1], meta["pixels_per_unit"]
    return int(kinds[round((y - y0) * r), round((x - x0) * r)])


def label_at(out_dir: Path, x: float, y: float) -> int:
    """Zone index (1-based) at a source point; 0 = no zone."""
    import numpy as np

    labels = np.load(out_dir / "sea_labels.npy")
    meta = sea_raster_meta(out_dir)
    x0, y0, r = meta["frame"][0], meta["frame"][1], meta["pixels_per_unit"]
    return int(labels[round((y - y0) * r), round((x - x0) * r)])


def read_graph(out_dir: Path) -> dict:
    return json.loads((out_dir / "graph.json").read_text(encoding="utf-8"))


def edges_by_key(graph: dict) -> dict:
    """``{(a_key, b_key): edge}`` lookup over a graph.json document."""
    by_id = {n["id"]: n["key"] for n in graph["nodes"]}
    return {
        (by_id[e["a"]], by_id[e["b"]]): e for e in graph["edges"]
    }


def graph_overrides(**kw) -> dict:
    """base_overrides tuned for small fixtures: modest margin, no smoothing."""
    data = base_overrides(sea_margin=3.0, sea_margin_smooth=0.0)
    data.update(kw)
    return data
