# ruff: noqa: E402 — startup must load_dotenv / set sys.path before app imports
"""
FastAPI application entry point.

Provides minimal app skeleton with config-safe startup validation.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

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
from modules._00_core.tick_recovery import recover_interrupted_ticks
from modules._01_map.api_service import get_api_payloads
from modules._01_map.router import router as map_router
from modules._01_map.startup import startup_map
from modules._02_bot.router import router as bot_router
from modules._02_bot.startup import start_runtime_if_ready, startup_bot
from modules._03_registry.profile_worker import start_profile_worker_if_ready
from modules._03_registry.router import router as registry_router
from modules._03_registry.startup import startup_registry
from modules._04_orders.router import router as orders_router
from modules._04_orders.startup import (
    register_orders_extensions,
    startup_orders,
)
from modules._04_orders.worker import start_orders_worker_if_ready

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_HANDLER_NAME = "goliath-root"


def configure_logging() -> None:
    """
    Point the root logger at stderr so app log lines reach
    ``docker compose logs``.

    Uvicorn configures only its own ``uvicorn.*`` loggers, so without a
    root handler every ``modules.*``/``core.*`` record below WARNING is
    dropped. One named handler with a readable single-line format —
    repeated calls never stack a second handler, and uvicorn's loggers
    keep their own handlers with ``propagate=False``, so no line prints
    twice. ``LOG_LEVEL`` selects the level (default INFO; an unknown
    value falls back to INFO). ``httpx``/``httpcore`` stay at WARNING:
    their INFO lines print full request URLs, query strings included.
    """
    raw_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelNamesMapping().get(raw_level, logging.INFO)

    root = logging.getLogger()
    if not any(h.name == _LOG_HANDLER_NAME for h in root.handlers):
        handler = logging.StreamHandler()
        handler.name = _LOG_HANDLER_NAME
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.

    Validates configuration on startup to fail fast if balance values are invalid.
    """
    configure_logging()

    # DEP-4: refuse to boot a strict-mode deployment (APP_ENV=production
    # and friends) on dev-grade secrets or a local database. Runs before
    # anything else so a misconfigured prod dies immediately.
    validate_production_environment(os.environ)

    # Validate core configuration at startup
    try:
        config_path = Path(__file__).parent.parent.parent / "configs" / "00_core.yaml"
        config = CoreConfig.from_yaml(str(config_path))
        print(
            f"Configuration validated successfully: {config.model_dump_json(indent=2)}"
        )
    except ValidationError as e:
        print(f"Configuration validation failed: {e}")
        raise
    except FileNotFoundError as e:
        print(f"Configuration file not found: {e}")
        raise

    init_engine(os.environ["DATABASE_URL"])

    # Deploy backlog: a container killed mid-tick leaves RUNNING
    # tick_log rows forever. Under the tick's own advisory lock, mark
    # them FAILED before the scheduler can start — a tick alive on
    # another instance holds the lock and nothing is touched.
    await recover_interrupted_ticks(get_session_context)

    # Handlers must be registered before the scheduler fires its first tick.
    register_tick_handlers()
    register_admin_hooks()

    # 01_map Spec Part 2 "Порядок запуска": load -> sync -> INV-M5 ->
    # register hooks. Runs before the scheduler so no tick (and no
    # request) can fire while the extension points are half-wired.
    await startup_map()

    # Spec 04_orders D11: the module's extension points (Registry table
    # source; bot notification types from Issue 6) must exist strictly
    # before startup_bot() and startup_registry() validate their
    # registries against their configs.
    register_orders_extensions()

    # Spec 02_bot 2.5: config validation + registry/hook wiring only —
    # no background tasks or routes yet (Issues 3–4). Runs even with
    # BOT_ENABLED=false: a broken YAML must still stop the server.
    startup_bot()

    # Spec Part 5: the manifest/geometry bodies and the manifest ETag
    # are built once here, never per request.
    get_api_payloads()

    # Spec 03_registry 2.5: config validation + source-registry wiring —
    # after every other startup_* so future modules can register their
    # sources first. The loaded CoreConfig is handed over so the table
    # sources never re-read 00_core.yaml per request.
    startup_registry(config)

    # Spec 04_orders D11: after all other startup_* — loads and keeps
    # OrdersConfig (a broken YAML stops the boot) and the VK-article
    # allowed hosts snapshot; registers the admin hooks.
    startup_orders()

    # Stamp the heartbeat so a fresh process reports scheduler "ok" on
    # /api/v1/health before the loop's first wake instead of "never".
    heartbeat.touch()
    scheduler_task = asyncio.create_task(scheduler_loop(), name="tick-scheduler")

    # Spec 02_bot 2.5 step 3: READY starts the BotRuntime right after
    # the tick scheduler; OFF/MISCONFIGURED start nothing (INV-B10).
    bot_runtime = await start_runtime_if_ready(get_session_context)

    # Spec 03_registry 2.4: the profile worker starts right after the
    # bot runtime; OFF/NO_TOKEN start nothing and never affect boot
    # (INV-R6).
    profile_worker = await start_profile_worker_if_ready(get_session_context)

    # Spec 04_orders 2.3: the retry/reminder worker starts after
    # startup_orders() loaded the config — the module's conscious
    # exception from the Tick DAG (D3).
    orders_worker = await start_orders_worker_if_ready(get_session_context)

    yield

    scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler_task
    if bot_runtime is not None:
        await bot_runtime.stop()
    if profile_worker is not None:
        await profile_worker.stop()
    if orders_worker is not None:
        await orders_worker.stop()
    await get_engine().dispose()


app = FastAPI(
    title="Project Goliath API",
    description="Backend for turn-based strategy game",
    version="0.8.13",
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
app.include_router(registry_router)
app.include_router(orders_router)

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
    "SHORT_NAME_TAKEN": 409,
    "COLOR_TAKEN": 409,
    "COLOR_TOO_CLOSE": 409,
    "PROVINCE_TAKEN": 409,
    "NATION_ALREADY_EXISTS": 409,
    "PROVINCE_NOT_FOUND": 404,
    "NATION_NOT_FOUND": 404,
    "GAME_CLOCK_NOT_FOUND": 404,
    "PROVINCE_COUNT_OUT_OF_RANGE": 422,
    "LEADER_NAME_INVALID": 422,
    "LEADER_TITLE_INVALID": 422,
    "HISTORY_URL_INVALID": 422,
    "ANTHEM_URL_INVALID": 422,
    "SHORT_NAME_INVALID": 422,
    "GENDER_INVALID": 422,
    "SUCCESSION_INVALID": 422,
    "MOTTO_INVALID": 422,
    "DESCRIPTION_INVALID": 422,
    "LEADER_BIO_INVALID": 422,
    "FLAG_INVALID": 422,
    "PORTRAIT_INVALID": 422,
    "CAPITAL_NAME_INVALID": 422,
    "CAPITAL_NOT_IN_PROVINCES": 422,
    "PROVINCE_NOT_LAND": 422,
    "STARTING_GROUP_NOT_CONNECTED": 422,
    "TURN_OUT_OF_RANGE": 422,
    "MAP_VERSION_UNKNOWN": 404,
    "REGISTRY_TABLE_NOT_FOUND": 404,
    "REGISTRY_PROVIDER_FAILED": 500,
    "ORDER_NATION_REQUIRED": 403,
    "ORDER_AUTHOR_LIMIT_REACHED": 409,
    "ORDER_TITLE_INVALID": 422,
    "ORDER_SUMMARY_INVALID": 422,
    "ORDER_URL_INVALID": 422,
    "ORDER_NOT_FOUND": 404,
    "ORDER_VERDICT_FORBIDDEN": 403,
    "ORDER_VERDICT_EXISTS": 409,
    "ORDER_NUMBER_CONFLICT": 500,
    "PLAYER_NOT_FOUND": 404,
    "CONFIRMATION_MISMATCH": 422,
    "CANNOT_DELETE_SELF": 409,
    "CANNOT_DELETE_ADMIN": 409,
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
