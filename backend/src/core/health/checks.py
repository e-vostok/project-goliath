"""
Dependency probes behind GET /api/v1/health.

Each check degrades to a bounded status word and never raises into the
handler: the endpoint's whole point is to answer 503 with a body, not
to bubble a traceback. No exception text, URLs or versions ever leave
this module — the response only ever contains the status words
"ok" / "fail" / "stale" / "never".
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from core.db import get_session_context
from core.tick import heartbeat

logger = logging.getLogger(__name__)

DB_CHECK_TIMEOUT_SECONDS = 3.0


async def database_status() -> str:
    """Return "ok" when SELECT 1 completes within the timeout, else "fail"."""

    async def _ping() -> None:
        async with get_session_context() as session:
            await session.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=DB_CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.exception("Health check: database probe failed")
        return "fail"
    return "ok"


def scheduler_status(max_age_seconds: float) -> str:
    """
    "never" before the first heartbeat, "stale" past the threshold,
    else "ok".

    The threshold lives in configs/00_core.yaml
    (tick.health_max_heartbeat_age_seconds) and must exceed
    retry_delay_seconds + heartbeat_interval_seconds: during a DB outage
    the loop touches the heartbeat only once per retry cycle, so a
    tighter threshold would flap the health check on a recoverable
    transient.
    """
    age = heartbeat.age_seconds()
    if age is None:
        return "never"
    return "stale" if age > max_age_seconds else "ok"
