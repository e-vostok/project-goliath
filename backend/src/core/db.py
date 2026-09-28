"""
Async SQLAlchemy engine and session factory.

Provides the base declarative class and async session management
for the entire application.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import AsyncContextManager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


_engine = None
_async_session_maker = None


def init_engine(database_url: str) -> None:
    """Initialize the async SQLAlchemy engine from a database URL."""
    global _engine, _async_session_maker
    _engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )
    _async_session_maker = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def get_engine():
    """Get the initialized SQLAlchemy engine."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return _engine


def get_session_maker():
    """Get the async session maker."""
    if _async_session_maker is None:
        raise RuntimeError("Session maker not initialized. Call init_engine() first.")
    return _async_session_maker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection helper for FastAPI routes."""
    if _async_session_maker is None:
        raise RuntimeError("Session maker not initialized. Call init_engine() first.")
    
    async with _async_session_maker() as session:
        yield session


def get_session_context() -> AsyncContextManager[AsyncSession]:
    """Get a session context manager for use outside FastAPI dependencies."""
    if _async_session_maker is None:
        raise RuntimeError("Session maker not initialized. Call init_engine() first.")
    
    return _async_session_maker()
