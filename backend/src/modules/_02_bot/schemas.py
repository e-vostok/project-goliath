"""Response schemas of module 02_bot (Spec 5.2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ConsentStateLiteral = Literal["UNKNOWN", "ALLOWED", "DENIED"]


class BotStatusResponse(BaseModel):
    """``GET /bot/status`` and ``POST /bot/consent/refresh`` body."""

    enabled: bool
    consent: ConsentStateLiteral
    stale: bool
    throttled: bool
    registration_requires_consent: bool
    chat_url: str | None
    consent_poll_interval_seconds: int | None
    consent_poll_timeout_seconds: int | None
