"""
Admin authorization dependency.

The admin allowlist is operational config (who may operate the panel), not
game balance, so it is read directly from the ADMIN_VK_USER_IDS environment
variable rather than a module config_schema. Since 0.11.0 unit 3 the env
allowlist is complemented by admin_grants rows in the database — the
session-aware is_admin_user/require_admin check both on every request.
"""

from __future__ import annotations

import os

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security import SecurityError
from core.security.dependencies import get_current_player
from modules._00_core.models import Player


class AdminRequiredError(SecurityError):
    """Raised when an authenticated player is not on the admin allowlist."""

    def __init__(self, message: str = "Admin privileges required"):
        super().__init__(message, "ADMIN_REQUIRED")


def _admin_vk_user_ids() -> set[int]:
    """
    Parse the ADMIN_VK_USER_IDS allowlist at call time.

    The variable is a comma-separated list of VK user IDs
    (e.g. "12345,67890"). Empty or missing means an empty allowlist: the
    check fails closed and no one is admin. Malformed entries raise
    ValueError, which also fails closed (no admin access is granted).
    """
    raw = os.environ.get("ADMIN_VK_USER_IDS") or ""
    return {int(part.strip()) for part in raw.split(",") if part.strip()}


def is_admin_vk_user(vk_user_id: int) -> bool:
    """
    Whether a VK user id is on the env allowlist (call-time read).

    Sync env-only helper for callers that have no session — it does NOT
    see admin_grants rows; session-aware callers must use is_admin_user.
    """
    return vk_user_id in _admin_vk_user_ids()


async def is_admin_user(session: AsyncSession, vk_user_id: int) -> bool:
    """
    Whether a VK user id has admin rights: on the env allowlist OR
    holding an admin_grants row. The grant is read from the database on
    every call, so a revoked admin loses access immediately.
    """
    if is_admin_vk_user(vk_user_id):
        return True
    # Function-level import: modules._00_core.admin_service itself
    # imports the env-allowlist helpers from this module.
    from modules._00_core.admin_service import AdminGrantService

    return await AdminGrantService.is_granted(session, vk_user_id)


async def require_admin(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
) -> Player:
    """
    FastAPI dependency: resolve the current player and require admin rights.

    Reuses get_current_player, so a missing/invalid Authorization header
    still raises UnauthorizedError before the allowlist is checked. The
    check accepts env allowlist members and database-granted admins
    (admin_grants), re-read on every request.

    Raises:
        AdminRequiredError: If the player is neither allowlisted nor granted.
    """
    if not await is_admin_user(session, player.vk_user_id):
        raise AdminRequiredError()
    return player
