"""
FastAPI application entry point.

Provides minimal app skeleton with config-safe startup validation.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from pydantic import ValidationError

from modules._00_core.config_schema import CoreConfig


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
    
    yield


app = FastAPI(
    title="Project Goliath API",
    description="Backend for turn-based strategy game",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
