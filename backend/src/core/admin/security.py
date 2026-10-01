"""
Admin authorization dependency.

The admin allowlist is operational config (who may operate the panel), not
game balance, so it is read directly from the ADMIN_VK_USER_IDS environment
variable rather than a module config_schema.
"""

from __future__ import annotations

import os

from fastapi import Depends

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


async def require_admin(player: Player = Depends(get_current_player)) -> Player:
    """
    FastAPI dependency: resolve the current player and require admin rights.

    Reuses get_current_player, so a missing/invalid Authorization header
    still raises UnauthorizedError before the allowlist is checked.

    Raises:
        AdminRequiredError: If the player's vk_user_id is not allowlisted.
    """
    if player.vk_user_id not in _admin_vk_user_ids():
        raise AdminRequiredError()
    return player
