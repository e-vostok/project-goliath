"""
Shared helpers for the 01_map loader/service tests (Issue 2).

Anti-Mock Guard: every test loads the real hand-made fixture directory
``tests/fixtures/map_mini/`` (or the real ``data/map/``) — nothing is
mocked. Negative tests copy the fixture into ``tmp_path`` and break
exactly one thing; ``fix_*`` helpers re-pin the affected manifest/
geometry hashes so the intended check is the one that fires.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from modules._01_map.config_schema import MapConfig
from modules._01_map.hashing import (
    INPUT_HASH_RULES,
    geometry_version,
    input_sha256,
)
from modules._01_map.loader import load_map_data
from modules._01_map.service import MapService

FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "map_mini"
)
REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_DATA_DIR = REPO_ROOT / "data" / "map"

_INPUT_REL = {
    "source": "source/map.svg",
    "boundary": "boundary.yaml",
    "overrides": "overrides.yaml",
    "ids_lock": "ids.lock.json",
}


def copy_map_mini(dst: Path) -> Path:
    """Copy the fixture tree to ``dst``; returns the copy's path."""
    target = dst / "map_mini"
    shutil.copytree(FIXTURE_DIR, target)
    return target


def map_config(**limit_overrides: int) -> MapConfig:
    """The real ``configs/01_map.yaml``, optionally with patched limits."""
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    if limit_overrides:
        config = config.model_copy(
            update={
                "limits": config.limits.model_copy(
                    update=limit_overrides
                )
            }
        )
    return config


def load_manifest(data_dir: Path) -> dict:
    return json.loads(
        (data_dir / "manifest.json").read_text(encoding="utf-8")
    )


def save_manifest(data_dir: Path, doc: dict) -> None:
    (data_dir / "manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_geometry(data_dir: Path) -> dict:
    return json.loads(
        (data_dir / "geometry.json").read_text(encoding="utf-8")
    )


def save_geometry(data_dir: Path, doc: dict) -> None:
    (data_dir / "geometry.json").write_text(
        json.dumps(doc, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_lock(data_dir: Path) -> dict:
    return json.loads(
        (data_dir / "ids.lock.json").read_text(encoding="utf-8")
    )


def save_lock(data_dir: Path, doc: dict) -> None:
    (data_dir / "ids.lock.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def fix_input_hashes(data_dir: Path) -> None:
    """Re-pin ``manifest.inputs_sha256`` to the input files on disk."""
    doc = load_manifest(data_dir)
    doc["inputs_sha256"] = {
        name: input_sha256(data_dir / _INPUT_REL[name], rule)
        for name, rule in INPUT_HASH_RULES.items()
    }
    save_manifest(data_dir, doc)


def fix_geometry_pin(data_dir: Path) -> None:
    """Re-pin ``geometry.version`` and ``manifest.geometry_version``."""
    geom = load_geometry(data_dir)
    geom["version"] = geometry_version(geom["outside"], geom["paths"])
    save_geometry(data_dir, geom)
    doc = load_manifest(data_dir)
    doc["geometry_version"] = geom["version"]
    save_manifest(data_dir, doc)


@pytest.fixture
def mini_dir(tmp_path) -> Path:
    """A writable copy of the hand-made mini map fixture."""
    return copy_map_mini(tmp_path)


@pytest.fixture
def config() -> MapConfig:
    """The real ``configs/01_map.yaml``."""
    return map_config()


@pytest.fixture
def mini_service(mini_dir, config) -> MapService:
    return MapService(load_map_data(mini_dir, config), config)
