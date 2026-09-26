"""
JWT session tokens.

Short-lived Bearer tokens issued after successful VK signature
validation. The signing secret is read from the JWT_SECRET_KEY
environment variable; the TTL comes from CoreConfig.auth.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from core.security import SecurityError

_ALGORITHM = "HS256"


class InvalidTokenError(SecurityError):
    """Raised when a Bearer token is missing, malformed, expired, or forged."""

    def __init__(self, message: str = "Token is invalid or expired"):
        super().__init__(message, "UNAUTHORIZED")


def issue_token(player_id: str, ttl_minutes: int) -> str:
    """
    Issue a signed JWT for the given player.

    Args:
        player_id: The player UUID to embed as the token subject.
        ttl_minutes: Token lifetime in minutes.

    Returns:
        The encoded JWT string.
    """
    secret = os.environ["JWT_SECRET_KEY"]
    now = datetime.now(timezone.utc)
    payload = {
        "sub": player_id,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return pyjwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_token(token: str) -> str:
    """
    Decode and validate a Bearer token.

    Args:
        token: The encoded JWT string (without the "Bearer " prefix).

    Returns:
        The player_id stored in the token subject.

    Raises:
        InvalidTokenError: If the token is expired, forged, or malformed.
    """
    secret = os.environ["JWT_SECRET_KEY"]
    try:
        payload = pyjwt.decode(token, secret, algorithms=[_ALGORITHM])
    except pyjwt.PyJWTError as e:
        raise InvalidTokenError() from e

    player_id = payload.get("sub")
    if not player_id:
        raise InvalidTokenError("Token subject is missing")
    return player_id
