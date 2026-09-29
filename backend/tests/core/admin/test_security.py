"""
Tests for the require_admin dependency and the ADMIN_VK_USER_IDS allowlist.

Anti-Mock Guard: a minimal FastAPI app wires the real dependency chain
(require_admin -> get_current_player -> JWT decode -> Player lookup) against
the shared in-memory test DB. The app's real domain_error_handler is reused
so ADMIN_REQUIRED/UNAUTHORIZED map to their production status codes.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from core.admin.security import AdminRequiredError, require_admin
from core.db import get_session
from core.security import SecurityError
from core.security.dependencies import UnauthorizedError, get_current_player
from core.security.jwt import issue_token
from main import domain_error_handler
from modules._00_core.models import Player

TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    """Provide a JWT secret; default to an unset (empty) admin allowlist."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.delenv("ADMIN_VK_USER_IDS", raising=False)


@pytest_asyncio.fixture
async def admin_client(test_db_session):
    """HTTP client over a minimal app exposing a require_admin-protected route."""
    test_app = FastAPI()
    test_app.add_exception_handler(SecurityError, domain_error_handler)

    @test_app.get("/admin-probe")
    async def admin_probe(player: Player = Depends(require_admin)):
        return {"vk_user_id": player.vk_user_id}

    async def _override_get_session():
        yield test_db_session

    test_app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        yield client
    test_app.dependency_overrides.clear()


def bearer_headers(player_id: str) -> dict[str, str]:
    """Build an Authorization header with a real issued JWT."""
    token = issue_token(player_id, ttl_minutes=60)
    return {"Authorization": f"Bearer {token}"}


async def seed_player(session, vk_user_id: int) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


class TestRequireAdmin:
    """Tests for the require_admin dependency."""

    @pytest.mark.asyncio
    async def test_allowlisted_admin_passes(
        self, admin_client, test_db_session, monkeypatch
    ):
        """A player whose vk_user_id is allowlisted reaches the handler."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "111, 222")
        player = await seed_player(test_db_session, vk_user_id=111)

        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )

        assert response.status_code == 200
        assert response.json() == {"vk_user_id": 111}

    @pytest.mark.asyncio
    async def test_non_allowlisted_returns_403(
        self, admin_client, test_db_session, monkeypatch
    ):
        """An authenticated but non-allowlisted player gets ADMIN_REQUIRED."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "111, 222")
        player = await seed_player(test_db_session, vk_user_id=999)

        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_missing_authorization_returns_401(self, admin_client):
        """No Authorization header: get_current_player fails first with 401.

        Proves the dependency chain works end-to-end: require_admin sits on
        top of the real get_current_player, so unauthenticated requests are
        rejected as UNAUTHORIZED before the allowlist is ever consulted.
        """
        response = await admin_client.get("/admin-probe")

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHORIZED"

    @pytest.mark.asyncio
    async def test_empty_allowlist_fails_closed(
        self, admin_client, test_db_session
    ):
        """With ADMIN_VK_USER_IDS unset, every real vk_user_id is rejected."""
        player = await seed_player(test_db_session, vk_user_id=111)

        response = await admin_client.get(
            "/admin-probe", headers=bearer_headers(player.id)
        )

        assert response.status_code == 403
        assert response.json()["code"] == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_direct_call_returns_player(
        self, test_db_session, monkeypatch
    ):
        """require_admin returns the resolved Player for an allowlisted id."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "555")
        player = await seed_player(test_db_session, vk_user_id=555)

        result = await require_admin(player=player)

        assert result is player

    @pytest.mark.asyncio
    async def test_direct_call_raises_admin_required(
        self, test_db_session, monkeypatch
    ):
        """require_admin raises AdminRequiredError for a non-allowlisted id."""
        monkeypatch.setenv("ADMIN_VK_USER_IDS", "555")
        player = await seed_player(test_db_session, vk_user_id=777)

        with pytest.raises(AdminRequiredError) as exc_info:
            await require_admin(player=player)

        assert exc_info.value.code == "ADMIN_REQUIRED"

    @pytest.mark.asyncio
    async def test_upstream_dependency_raises_unauthorized(
        self, test_db_session
    ):
        """get_current_player still raises UnauthorizedError on no header."""
        with pytest.raises(UnauthorizedError):
            await get_current_player(
                authorization=None, session=test_db_session
            )
