"""
Extension-point implementations of 01_map, registered at startup
(Spec Part 2 "Порядок запуска").

- ownership listener -> writes map_ownership_log rows (INV-M7);
- registration check "after_free"  -> PROVINCE_NOT_LAND;
- registration check "after_count" -> STARTING_GROUP_NOT_CONNECTED;
- admin reset hook -> clears the journal (INV-M8).

Nothing here commits: listeners run inside the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    OwnershipChange,
    register_ownership_listener,
    register_registration_check,
)
from modules._00_core.models import Province
from modules._01_map.config_schema import MapConfig
from modules._01_map.errors import (
    ProvinceNotLandError,
    StartingGroupNotConnectedError,
)
from modules._01_map.map_data import KIND_LAND
from modules._01_map.ownership_service import clear_all, record_changes
from modules._01_map.service import MapService

MODULE_SLUG = "01_map"


async def ownership_log_listener(
    session: AsyncSession, changes: Sequence[OwnershipChange]
) -> None:
    """Append one map_ownership_log row per change (same transaction)."""
    await record_changes(session, changes)


async def check_starting_group_land(
    session: AsyncSession, provinces: Sequence[Province]
) -> None:
    """
    Stage "after_free": every chosen province must be a LAND node.

    Existence/freedom already ran in core, so only the node's kind is
    checked here; unknown ids are core's business, not this check's.
    """
    sea_ids = [p.id for p in provinces if p.kind != KIND_LAND]
    if sea_ids:
        raise ProvinceNotLandError(sea_ids)


def _make_connected_group_check(
    map_service: MapService, config: MapConfig
):
    async def check(
        session: AsyncSession, provinces: Sequence[Province]
    ) -> None:
        """
        Stage "after_count": the starting group must be connected over
        land+strait edges when starting_group.require_connected is set.
        """
        if not config.starting_group.require_connected:
            return
        components = map_service.group_components(
            p.id for p in provinces
        )
        if len(components) > 1:
            raise StartingGroupNotConnectedError(len(components))

    return check


async def reset_ownership_log(session: AsyncSession) -> None:
    """World-reset hook: wipe the journal — reset writes no history."""
    await clear_all(session)


def register_map_hooks(map_service: MapService, config: MapConfig) -> None:
    """
    Register all 01_map extension points. Registration is idempotent:
    named registries replace same-name entries, and the reset hook is
    guarded by membership — repeated startup does not double-register.
    """
    register_ownership_listener(
        f"{MODULE_SLUG}.ownership_log", ownership_log_listener
    )
    register_registration_check(
        STAGE_AFTER_FREE,
        f"{MODULE_SLUG}.land_only",
        check_starting_group_land,
    )
    register_registration_check(
        STAGE_AFTER_COUNT,
        f"{MODULE_SLUG}.connected_group",
        _make_connected_group_check(map_service, config),
    )
    if MODULE_SLUG not in AdminRegistry.get_reset_hooks():
        AdminRegistry.register_reset(MODULE_SLUG, reset_ownership_log)
