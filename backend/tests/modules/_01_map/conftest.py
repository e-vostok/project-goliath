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
import pytest_asyncio

import modules._01_map.service as map_service_module
from core.admin.registry import AdminRegistry
from modules._00_core.hooks import (
    restore_extension_points,
    snapshot_extension_points,
)
from modules._00_core.service import NodeSpec, ProvinceService
from modules._01_map.config_schema import FrameConfig, MapConfig
from modules._01_map.hashing import (
    INPUT_HASH_RULES,
    borders_version,
    geometry_version,
    input_sha256,
)
from modules._01_map.hooks import register_map_hooks
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


# A frame inside the mini fixture's view_box [0, 0, 100, 80]: the real
# config's frame is calibrated to the real map (519.1, 20.9, 221.3,
# 217.3) and would fail the loader's frame-inside-view_box check here.
MINI_FRAME = FrameConfig(x=10.0, y=10.0, width=60.0, height=50.0)


def map_config(**limit_overrides: int) -> MapConfig:
    """The real ``configs/01_map.yaml`` with ``view.frame`` swapped for
    the mini-map frame, optionally with patched limits."""
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    config = config.model_copy(
        update={
            "view": config.view.model_copy(update={"frame": MINI_FRAME})
        }
    )
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


def load_borders(data_dir: Path) -> dict:
    return json.loads(
        (data_dir / "borders.json").read_text(encoding="utf-8")
    )


def save_borders(data_dir: Path, doc: dict) -> None:
    (data_dir / "borders.json").write_text(
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


def fix_borders_pin(data_dir: Path) -> None:
    """Re-pin ``borders.version`` and ``manifest.borders_version``.

    The borders version takes ``geometry_version`` as an input, so it
    must be re-pinned after ANY geometry re-pin as well as after direct
    borders edits.
    """
    borders = load_borders(data_dir)
    doc = load_manifest(data_dir)
    borders["version"] = borders_version(
        doc["geometry_version"], borders["pairs"], borders["coasts"]
    )
    save_borders(data_dir, borders)
    doc["borders_version"] = borders["version"]
    save_manifest(data_dir, doc)


def fix_geometry_pin(data_dir: Path) -> None:
    """Re-pin ``geometry.version`` and ``manifest.geometry_version``."""
    geom = load_geometry(data_dir)
    geom["version"] = geometry_version(
        geom["outside"], geom["paths"], geom["sea_water"]
    )
    save_geometry(data_dir, geom)
    doc = load_manifest(data_dir)
    doc["geometry_version"] = geom["version"]
    save_manifest(data_dir, doc)
    fix_borders_pin(data_dir)


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


@pytest.fixture
def flat_map_service(config) -> MapService:
    """MapService over the shared fixture dir — read-only, no copy."""
    return MapService(load_map_data(FIXTURE_DIR, config), config)


def map_config_disconnected() -> MapConfig:
    """A config copy with starting_group.require_connected = false."""
    config = map_config()
    return config.model_copy(
        update={
            "starting_group": config.starting_group.model_copy(
                update={"require_connected": False}
            )
        }
    )


async def sync_map_nodes(session, map_service: MapService) -> None:
    """Sync a MapService's nodes into provinces via the real path."""
    await ProvinceService.ensure_nodes(
        session,
        [
            NodeSpec(id=node.id, kind=node.kind)
            for node in map_service.all_nodes()
        ],
    )


@pytest.fixture
def extension_snapshot():
    """
    Snapshot/restore every registry the 01_map startup touches:
    the core extension points, the admin hooks, and the
    process-wide MapService singleton.
    """
    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_extensions = snapshot_extension_points()
    saved_service = map_service_module._instance
    yield
    restore_extension_points(saved_extensions)
    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    map_service_module._instance = saved_service


@pytest.fixture
def map_hooks(extension_snapshot, flat_map_service, config):
    """The real 01_map hooks registered over the mini-map service."""
    register_map_hooks(flat_map_service, config)
    return flat_map_service


@pytest_asyncio.fixture
async def map_db_session(test_db_session, flat_map_service):
    """In-memory DB with the mini-map nodes already synced in."""
    await sync_map_nodes(test_db_session, flat_map_service)
    return test_db_session
