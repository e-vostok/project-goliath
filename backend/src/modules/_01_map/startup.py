"""
Startup wiring of 01_map — Spec Part 2 "Порядок запуска".

Called from the application lifespan AFTER init_engine and AFTER the
core registries exist, BEFORE the scheduler starts:

1. load and validate ``configs/01_map.yaml`` (``MapConfig``);
2. ``load_map_data(data_dir, config)`` — ``data_dir`` is the
   ``MAP_DATA_DIR`` env var, else ``<repo>/data/map``;
3. ``ProvinceService.ensure_nodes(...)`` for every manifest node, then
   INV-M5: extra DB rows and kind mismatches are fatal with a message
   saying what to do;
4. register the ownership listener, the two registration checks and the
   reset hook; install the ``MapService`` singleton.

Any failure aborts startup with a single clear message (INV-M9): the
process never starts half-configured, and hooks are registered only
after the map was proven consistent with the database, so a failed boot
leaves the registries untouched.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from core.db import get_session_context
from modules._00_core.service import NodeSpec, ProvinceService
from modules._01_map.config_schema import MapConfig
from modules._01_map.hooks import register_map_hooks
from modules._01_map.loader import INV_M5, MapDataError, load_map_data
from modules._01_map.service import MapService, init_map_service

logger = logging.getLogger(__name__)

MAP_DATA_DIR_ENV = "MAP_DATA_DIR"

# This file: backend/src/modules/_01_map/startup.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data" / "map"

_MAX_LISTED = 10


def resolve_data_dir() -> Path:
    """MAP_DATA_DIR if set, else ``<repo>/data/map``."""
    raw = os.environ.get(MAP_DATA_DIR_ENV)
    return Path(raw) if raw else _DEFAULT_DATA_DIR


def _verify_inv_m5(result) -> None:
    """provinces == manifest, or startup dies here (INV-M5)."""
    problems: list[str] = []
    if result.extra_in_db:
        shown = result.extra_in_db[:_MAX_LISTED]
        problems.append(
            "provinces contains rows absent from manifest.json: "
            f"{shown} — run the world reset; the database likely belongs "
            "to another map"
        )
    if result.kind_mismatch:
        shown = result.kind_mismatch[:_MAX_LISTED]
        problems.append(
            "provinces kind differs from manifest.json for ids: "
            f"{shown} — the map data changed incompatibly; reconcile the "
            "map files or reset the world"
        )
    if problems:
        raise MapDataError(INV_M5, "; ".join(problems))


async def startup_map() -> MapService:
    """
    Boot the map module. Returns the installed MapService. Any failure
    (MapDataError, config validation, DB errors) propagates and aborts
    the lifespan — the app does not start half-configured.
    """
    config = MapConfig.from_yaml(MapConfig.get_default_config_path())
    data_dir = resolve_data_dir()
    map_data = load_map_data(data_dir, config)

    async with get_session_context() as session:
        result = await ProvinceService.ensure_nodes(
            session,
            [
                NodeSpec(id=node.id, kind=node.kind)
                for node in map_data.nodes.values()
            ],
        )
        _verify_inv_m5(result)
        await session.commit()

    # Only once the DB provably matches the manifest (INV-M5) may the
    # module claim its extension points and the process-wide singleton.
    service = MapService(map_data, config)
    register_map_hooks(service, config)
    init_map_service(service)
    logger.info(
        "01_map started: %d nodes from %s "
        "(%d added to provinces, %d already present)",
        len(map_data.nodes),
        data_dir,
        len(result.added),
        len(map_data.nodes) - len(result.added),
    )
    return service
