"""
GET /api/v1/health — deep health for deploy verification and monitors.

Public (no auth), always answered with Cache-Control: no-store. 200 only
when every check is "ok"; otherwise 503 with status "degraded" and the
per-check words. The body is deliberately minimal — no exception text,
URLs, versions or secrets — because it is reachable from the internet.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.health import checks
from modules._00_core.config_schema import CoreConfig

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def api_health() -> JSONResponse:
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    database = await checks.database_status()
    scheduler = checks.scheduler_status(
        config.tick.health_max_heartbeat_age_seconds
    )
    healthy = database == "ok" and scheduler == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "checks": {"database": database, "scheduler": scheduler},
        },
        headers={"Cache-Control": "no-store"},
    )
