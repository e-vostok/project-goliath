"""
Pytest configuration and fixtures for async tests.

Provides async SQLite in-memory database fixture with schema creation.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.db import Base


@pytest_asyncio.fixture(scope="function")
async def test_db_engine() -> AsyncGenerator[Any, None]:
    """
    Create an async SQLite in-memory database engine for testing.
    
    The database is created fresh for each test function.
    """
    database_url = "sqlite+aiosqlite:///:memory:"
    
    engine = create_async_engine(
        database_url,
        echo=False,
        future=True,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_db_session(test_db_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """
    Create an async session for the test database.
    
    Creates tables using SQLAlchemy metadata before yielding the session.
    Wraps each test in a transaction that gets rolled back.
    """
    session_maker = async_sessionmaker(
        test_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with session_maker() as session:
        # Begin a transaction
        await session.begin()
        
        yield session
        
        # Rollback the transaction to clean up
        await session.rollback()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Configure pytest-asyncio to use asyncio backend."""
    return "asyncio"
