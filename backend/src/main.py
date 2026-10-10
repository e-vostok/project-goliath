"""
FastAPI application entry point.

Provides minimal app skeleton with config-safe startup validation.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.gzip import GZipMiddleware

from core.admin.router import router as admin_router
from core.db import get_engine, get_session_context, init_engine
from core.health.router import router as health_router
from core.security import SecurityError
from core.security.startup_guard import validate_production_environment
from core.tick import heartbeat
from core.tick.scheduler import scheduler_loop
from modules._00_core.admin_hooks import register_admin_hooks
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import CoreDomainError
from modules._00_core.router import router as core_router
from modules._00_core.tick_handler import register_tick_handlers
from modules._01_map.api_service import get_api_payloads
from modules._01_map.router import router as map_router
from modules._01_map.startup import startup_map
from modules._02_bot.router import router as bot_router
from modules._02_bot.startup import start_runtime_if_ready, startup_bot


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    
    Validates configuration on startup to fail fast if balance values are invalid.
    """
    # DEP-4: refuse to boot a strict-mode deployment (APP_ENV=production
    # and friends) on dev-grade secrets or a local database. Runs before
    # anything else so a misconfigured prod dies immediately.
    validate_production_environment(os.environ)

    # Validate core configuration at startup
    try:
        config_path = Path(__file__).parent.parent.parent / "configs" / "00_core.yaml"
        config = CoreConfig.from_yaml(str(config_path))
        print(f"Configuration validated successfully: {config.model_dump_json(indent=2)}")
    except ValidationError as e:
        print(f"Configuration validation failed: {e}")
        raise
    except FileNotFoundError as e:
        print(f"Configuration file not found: {e}")
        raise

    init_engine(os.environ["DATABASE_URL"])

    # Handlers must be registered before the scheduler fires its first tick.
    register_tick_handlers()
    register_admin_hooks()

    # 01_map Spec Part 2 "Порядок запуска": load -> sync -> INV-M5 ->
    # register hooks. Runs before the scheduler so no tick (and no
    # request) can fire while the extension points are half-wired.
    await startup_map()

    # Spec 02_bot 2.5: config validation + registry/hook wiring only —
    # no background tasks or routes yet (Issues 3–4). Runs even with
    # BOT_ENABLED=false: a broken YAML must still stop the server.
    startup_bot()

    # Spec Part 5: the manifest/geometry bodies and the manifest ETag
    # are built once here, never per request.
    get_api_payloads()

    # Stamp the heartbeat so a fresh process reports scheduler "ok" on
    # /api/v1/health before the loop's first wake instead of "never".
    heartbeat.touch()
    scheduler_task = asyncio.create_task(scheduler_loop(), name="tick-scheduler")

    # Spec 02_bot 2.5 step 3: READY starts the BotRuntime right after
    # the tick scheduler; OFF/MISCONFIGURED start nothing (INV-B10).
    bot_runtime = await start_runtime_if_ready(get_session_context)

    yield

    scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler_task
    if bot_runtime is not None:
        await bot_runtime.stop()
    await get_engine().dispose()


app = FastAPI(
    title="Project Goliath API",
    description="Backend for turn-based strategy game",
    version="0.5.11",
    lifespan=lifespan,
)

# Spec 01_map Part 5 (§3.6 of the Issue-4 TZ): the map manifest (~1100
# nodes) and geometry (~1.9 MB) responses go through gzip.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(core_router)
app.include_router(admin_router)
app.include_router(health_router)
app.include_router(map_router)
app.include_router(bot_router)

# Maps domain error codes to HTTP status codes (Spec Part 5).
# UNAUTHORIZED and GAME_CLOCK_NOT_FOUND are additions to the spec's
# original list: Bearer auth failures need a 401, and a missing
# game_clock singleton needs a 404.
_ERROR_CODE_STATUS = {
    "INVALID_SIGNATURE": 401,
    "TIMESTAMP_EXPIRED": 401,
    "UNAUTHORIZED": 401,
    "ADMIN_REQUIRED": 403,
    "RESET_DISABLED": 403,
    "CONSENT_REQUIRED": 403,
    "CONFIRM_REQUIRED": 400,
    "MODULE_NOT_FOUND": 404,
    "BOT_DISABLED": 409,
    "TICK_IN_PROGRESS": 409,
    "NAME_TAKEN": 409,
    "COLOR_TAKEN": 409,
    "PROVINCE_TAKEN": 409,
    "NATION_ALREADY_EXISTS": 409,
    "PROVINCE_NOT_FOUND": 404,
    "NATION_NOT_FOUND": 404,
    "GAME_CLOCK_NOT_FOUND": 404,
    "PROVINCE_COUNT_OUT_OF_RANGE": 422,
    "LEADER_NAME_INVALID": 422,
    "LEADER_TITLE_INVALID": 422,
    "HISTORY_URL_INVALID": 422,
    "PROVINCE_NOT_LAND": 422,
    "STARTING_GROUP_NOT_CONNECTED": 422,
    "TURN_OUT_OF_RANGE": 422,
    "MAP_VERSION_UNKNOWN": 404,
}


@app.exception_handler(CoreDomainError)
@app.exception_handler(SecurityError)
async def domain_error_handler(
    request: Request,
    exc: CoreDomainError | SecurityError,
) -> JSONResponse:
    """Map domain/security errors to the ErrorResponse JSON shape."""
    content: dict = {"detail": exc.message, "code": exc.code}
    details = getattr(exc, "details", None)
    if details:
        content["details"] = details
    return JSONResponse(
        status_code=_ERROR_CODE_STATUS.get(exc.code, 500),
        content=content,
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
