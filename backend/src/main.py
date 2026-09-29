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

from core.db import get_engine, init_engine
from core.security import SecurityError
from core.tick.scheduler import scheduler_loop
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import CoreDomainError
from modules._00_core.router import router as core_router
from modules._00_core.tick_handler import register_tick_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    
    Validates configuration on startup to fail fast if balance values are invalid.
    """
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

    scheduler_task = asyncio.create_task(scheduler_loop(), name="tick-scheduler")

    yield

    scheduler_task.cancel()
    with suppress(asyncio.CancelledError):
        await scheduler_task
    await get_engine().dispose()


app = FastAPI(
    title="Project Goliath API",
    description="Backend for turn-based strategy game",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(core_router)

# Maps domain error codes to HTTP status codes (Spec Part 5).
# UNAUTHORIZED and GAME_CLOCK_NOT_FOUND are additions to the spec's
# original list: Bearer auth failures need a 401, and a missing
# game_clock singleton needs a 404.
_ERROR_CODE_STATUS = {
    "INVALID_SIGNATURE": 401,
    "TIMESTAMP_EXPIRED": 401,
    "UNAUTHORIZED": 401,
    "ADMIN_REQUIRED": 403,
    "NAME_TAKEN": 409,
    "COLOR_TAKEN": 409,
    "PROVINCE_TAKEN": 409,
    "NATION_ALREADY_EXISTS": 409,
    "PROVINCE_NOT_FOUND": 404,
    "NATION_NOT_FOUND": 404,
    "GAME_CLOCK_NOT_FOUND": 404,
    "PROVINCE_COUNT_OUT_OF_RANGE": 422,
}


@app.exception_handler(CoreDomainError)
@app.exception_handler(SecurityError)
async def domain_error_handler(
    request: Request,
    exc: CoreDomainError | SecurityError,
) -> JSONResponse:
    """Map domain/security errors to the ErrorResponse JSON shape."""
    return JSONResponse(
        status_code=_ERROR_CODE_STATUS.get(exc.code, 500),
        content={"detail": exc.message, "code": exc.code},
    )


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
