"""
FastAPI auth dependencies.

get_current_player is shared infrastructure: every module's protected
routes reuse it to resolve the Bearer JWT to a Player row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.security import SecurityError
from core.security.jwt import decode_token
from modules._00_core.models import Player


class UnauthorizedError(SecurityError):
    """Raised when a request lacks valid authentication."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, "UNAUTHORIZED")


async def get_current_player(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> Player:
    """
    Resolve the Bearer JWT in the Authorization header to a Player.

    The header is optional at the FastAPI level so that a missing header
    produces a 401 (not FastAPI's default 422 for missing required headers).

    Raises:
        UnauthorizedError: On missing/malformed header or unknown player.
        InvalidTokenError: On expired/forged token (code UNAUTHORIZED).
    """
    if authorization is None or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")

    token = authorization[len("Bearer "):]
    player_id = decode_token(token)

    player = await session.get(Player, player_id)
    if player is None:
        raise UnauthorizedError("Player not found")

    return player
