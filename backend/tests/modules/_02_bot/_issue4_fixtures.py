"""
Fixtures for the Issue-4 suite of 02_bot — loaded via ``pytest_plugins``
so helpers and fixtures can live outside the shared conftest (the
``client`` fixture mirrors ``tests/modules/_00_core/test_router.py``;
``fake_vk_runtime`` installs a prepared-but-not-started runtime on the
FakeVk transport so on-demand VK checks run against the real wiring).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from core.db import get_session
from main import app
from modules._02_bot.runtime import BotRuntime, install_runtime
from modules._02_bot.settings import read_bot_env
from tests.fixtures.fake_vk import FakeVk
from tests.modules._02_bot._issue3_support import make_session_factory


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """A real-length JWT secret for issued Bearer tokens."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-secret-key-32-bytes-long!!")


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test session."""
    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def fake_vk_runtime(bot_started, test_db_engine):
    """
    A prepared (not started) runtime on the FakeVk transport, installed
    as the process runtime — on-demand VK checks reach it, no
    background task runs.
    """
    env = read_bot_env()
    fake = FakeVk()
    runtime = BotRuntime(
        bot_started,
        env,
        make_session_factory(test_db_engine),
        transport=fake.transport,
    )
    runtime.prepare()
    install_runtime(runtime)
    yield fake, runtime
    install_runtime(None)
    await runtime.aclose()
