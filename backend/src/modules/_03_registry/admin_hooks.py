"""
Admin hooks of module 03_registry (Spec 5.4).

- State view ``"03_registry"``: a JSON-able snapshot — the configured
  table ids, player and nation counts, profile counts per FSM status,
  the profile worker mode (``OFF`` until Issue 4) and the moment of the
  worker's last cycle. No names, photo urls or VK ids (INV-R2).
- No reset hook (D9): VK profiles describe people, not world state — a
  world reset keeps them.

``register_registry_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.service import NationService, PlayerService
from modules._03_registry.models import RegistryVkProfile

MODULE_SLUG = "03_registry"


async def registry_state_view(session: AsyncSession) -> dict:
    """Read-only snapshot of the module for the admin panel (Spec 5.4)."""
    # Local import: admin_hooks.py is imported by startup.py, so a
    # top-level import of the config holder would be a cycle.
    from modules._03_registry.startup import get_registry_config

    config = get_registry_config()

    # Player and nation counts go through the public read path of the
    # owning module — the registry never queries 00_core tables directly
    # (INV-R1).
    players_total = len(await PlayerService.list_for_registry(session))
    nations_total = len(await NationService.list_for_registry(session))

    profile_rows = await session.execute(
        select(RegistryVkProfile.status, func.count()).group_by(
            RegistryVkProfile.status
        )
    )
    profiles = {"PENDING": 0, "OK": 0, "UNAVAILABLE": 0}
    profiles.update(
        {status: count for status, count in profile_rows.all()}
    )

    return {
        "tables": [table.id for table in config.tables],
        "players_total": players_total,
        "nations_total": nations_total,
        "profiles": profiles,
        # The profile worker is Issue 4 — until then the module reports
        # a fixed OFF and no cycle has ever run.
        "profile_worker_mode": "OFF",
        "profile_worker_last_cycle_at": None,
    }


def register_registry_admin_hooks() -> None:
    """Register the admin state view; safe to call on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, registry_state_view)
