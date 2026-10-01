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


@pytest.fixture
def run_pipeline(tmp_path):
    def _run(data_dir: Path, check: bool = False) -> tuple[int, Path]:
        out_dir = tmp_path / "out"
        return run_nodes(data_dir, out_dir, check), out_dir

    return _run
