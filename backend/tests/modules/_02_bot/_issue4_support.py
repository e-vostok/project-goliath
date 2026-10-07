"""
Shared helpers for the Issue-4 suite of 02_bot — request bodies, JWT
headers and row seeding. Fixtures live in ``_issue4_fixtures.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.security.jwt import issue_token
from modules._00_core.config_schema import CoreConfig
from modules._00_core.models import Player

# Values wired by the ``bot_env`` fixture of the module conftest.
GROUP_ID = "12345"
CALLBACK_SECRET = "test-callback-secret"
CONFIRMATION = "test-confirm"

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


def bearer_headers(player_id: str) -> dict[str, str]:
    """An Authorization header with a real issued JWT."""
    token = issue_token(player_id, CORE_CONFIG.auth.jwt_ttl_minutes)
    return {"Authorization": f"Bearer {token}"}


async def seed_player(session, vk_user_id: int = 12345) -> Player:
    """One player row, flushed into the caller's transaction."""
    player = Player(id=str(uuid.uuid4()), vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


def vk_body(
    event_type: str,
    *,
    event_id: str | None = None,
    obj: Any = "UNSET",
    group_id: int | str = 12345,
    secret: str | None = CALLBACK_SECRET,
) -> dict:
    """A Callback API request body in the VK envelope shape."""
    body: dict[str, Any] = {
        "type": event_type,
        "group_id": group_id,
    }
    if secret is not None:
        body["secret"] = secret
    if event_id is not None:
        body["event_id"] = event_id
    if obj != "UNSET":
        body["object"] = obj
    return body


def message_new_body(
    vk_user_id: int,
    event_id: str,
    *,
    text: str = "",
    payload: str | None = None,
    peer_id: int | None = None,
    out: int = 0,
) -> dict:
    """A ``message_new`` event body (API >= 5.103 wrapped shape)."""
    message: dict[str, Any] = {
        "from_id": vk_user_id,
        "peer_id": peer_id if peer_id is not None else vk_user_id,
        "out": out,
        "text": text,
    }
    if payload is not None:
        message["payload"] = payload
    return vk_body(
        "message_new",
        event_id=event_id,
        obj={"message": message, "client_info": {"button_actions": []}},
    )
