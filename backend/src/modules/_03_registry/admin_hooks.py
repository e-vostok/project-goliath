"""
Admin hooks of module 03_registry (Spec 5.4).

- State view ``"03_registry"``: a JSON-able snapshot — the configured
  table ids, player and nation counts, profile counts per FSM status,
  the real profile worker mode (``OFF``/``NO_TOKEN``/``RUNNING``) and
  the moment of the worker's last finished cycle (in memory, ``None``
  before the first). No names, photo urls or VK ids (INV-R2).
- No reset hook (D9): VK profiles describe people, not world state — a
  world reset keeps them.
- Player delete ``"03_registry.player_delete"``: removes the player's
  cached ``registry_vk_profiles`` row. Runs inside
  ``PlayerService.delete_player``'s transaction — a raise aborts the
  whole deletion (no per-hook savepoint).
- Player preview ``"03_registry"``: returns ``{"vk_profile_rows"}`` —
  0 or 1 — for the admin delete-preview; read-only.

``register_registry_admin_hooks`` is idempotent like the other modules'
registrars: membership check, never double-register.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.admin.registry import AdminRegistry
from modules._00_core.hooks import register_player_delete_hook
from modules._00_core.service import NationService, PlayerService
from modules._03_registry.models import RegistryVkProfile
from modules._03_registry.profile_worker import (
    get_last_cycle_at,
    get_worker_mode,
)

MODULE_SLUG = "03_registry"


async def registry_state_view(session: AsyncSession) -> dict:
    """Read-only snapshot of the module for the admin panel (Spec 5.4)."""
    # Local import: admin_hooks.py is imported by startup.py, so a
    # top-level import of the config holder would be a cycle.
    from modules._03_registry.startup import get_registry_config

    config = get_registry_config()

    # Player and nation counts go through the public read path of the
    # owning module — the registry never queries 00_core tables directly
    # (INV-R1), and the totals come back without loading any rows.
    players_total = await PlayerService.count(session)
    nations_total = await NationService.count(session)

    profile_rows = await session.execute(
        select(RegistryVkProfile.status, func.count()).group_by(
            RegistryVkProfile.status
        )
    )
    profiles = {"PENDING": 0, "OK": 0, "UNAVAILABLE": 0}
    profiles.update(
        {status: count for status, count in profile_rows.all()}
    )

    last_cycle = get_last_cycle_at()
    return {
        "tables": [table.id for table in config.tables],
        "players_total": players_total,
        "nations_total": nations_total,
        "profiles": profiles,
        "profile_worker_mode": get_worker_mode().value,
        "profile_worker_last_cycle_at": (
            last_cycle.isoformat() if last_cycle is not None else None
        ),
    }


async def registry_player_delete_preview(
    session: AsyncSession, player_id: str
) -> dict:
    """Whether the module keeps a cached VK profile for this player."""
    rows = (
        await session.execute(
            select(func.count())
            .select_from(RegistryVkProfile)
            .where(RegistryVkProfile.player_id == player_id)
        )
    ).scalar_one()
    return {"vk_profile_rows": rows}


async def registry_delete_player(
    session: AsyncSession, player_id: str
) -> None:
    """
    Remove the cached VK profile of one player (admin player deletion).

    An explicit DELETE, not FK cascade: SQLite may run without enforced
    foreign keys. Inside the caller's transaction; never commits, and a
    raise rolls the whole player deletion back.
    """
    await session.execute(
        delete(RegistryVkProfile).where(
            RegistryVkProfile.player_id == player_id
        )
    )


def register_registry_admin_hooks() -> None:
    """Register the admin hooks; safe to call on every app boot."""
    if MODULE_SLUG not in AdminRegistry.get_state_view_hooks():
        AdminRegistry.register_state_view(MODULE_SLUG, registry_state_view)
    if MODULE_SLUG not in AdminRegistry.get_player_preview_hooks():
        AdminRegistry.register_player_preview(
            MODULE_SLUG, registry_player_delete_preview
        )
    register_player_delete_hook(
        f"{MODULE_SLUG}.player_delete", registry_delete_player
    )
