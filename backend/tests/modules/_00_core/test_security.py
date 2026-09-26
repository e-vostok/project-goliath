"""
Tests for VK launch-params signature validation and JWT tokens.

Exercises the real cryptographic code paths (no mocks): signatures are
generated exactly as the VK client would, and tokens are issued/decoded
against a real secret from the environment.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

import pytest

from core.security.jwt import InvalidTokenError, decode_token, issue_token
from core.security.vk_signature import (
    InvalidSignatureError,
    TimestampExpiredError,
    validate_launch_params,
)

TEST_APP_SECRET = "test-vk-app-secret"
TEST_JWT_SECRET = "test-jwt-secret-key-32-bytes-long!!"
FRESHNESS_MINUTES = 30


def make_launch_params(
    vk_user_id: int = 12345,
    secret: str = TEST_APP_SECRET,
    vk_ts: int | None = None,
    **extra: str,
) -> str:
    """Build a signed launch-params query string, as the VK client would."""
    params = {
        "vk_user_id": str(vk_user_id),
        "vk_app_id": "777",
        "vk_platform": "desktop_web",
        "vk_ts": str(vk_ts if vk_ts is not None else int(time.time())),
    }
    params.update(extra)

    vk_params = sorted(
        (key, value) for key, value in params.items() if key.startswith("vk_")
    )
    base_string = urllib.parse.urlencode(vk_params)
    digest = hmac.new(
        secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256
    ).digest()
    sign = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    return urllib.parse.urlencode(params) + "&sign=" + sign


@pytest.fixture(autouse=True)
def jwt_secret_env(monkeypatch):
    """Provide a JWT signing secret for token tests."""
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


class TestValidateLaunchParams:
    """Tests for VK signature validation."""

    def test_valid_signature_returns_vk_user_id(self):
        """Valid launch params return the vk_user_id."""
        launch_params = make_launch_params(vk_user_id=424242)

        result = validate_launch_params(
            launch_params, TEST_APP_SECRET, FRESHNESS_MINUTES
        )

        assert result == 424242

    def test_invalid_signature_raises(self):
        """A wrong/missing signature is rejected."""
        launch_params = make_launch_params(secret="wrong-secret")

        with pytest.raises(InvalidSignatureError):
            validate_launch_params(
                launch_params, TEST_APP_SECRET, FRESHNESS_MINUTES
            )

    def test_tampered_param_raises(self):
        """Changing a vk_* param after signing invalidates the signature."""
        launch_params = make_launch_params(vk_user_id=111)
        launch_params = launch_params.replace("vk_user_id=111", "vk_user_id=999")

        with pytest.raises(InvalidSignatureError):
            validate_launch_params(
                launch_params, TEST_APP_SECRET, FRESHNESS_MINUTES
            )

    def test_expired_timestamp_raises(self):
        """A vk_ts older than the freshness window is rejected."""
        launch_params = make_launch_params(
            vk_ts=int(time.time()) - (FRESHNESS_MINUTES + 1) * 60
        )

        with pytest.raises(TimestampExpiredError):
            validate_launch_params(
                launch_params, TEST_APP_SECRET, FRESHNESS_MINUTES
            )

    def test_future_timestamp_raises(self):
        """A vk_ts in the future beyond the window is rejected."""
        launch_params = make_launch_params(
            vk_ts=int(time.time()) + (FRESHNESS_MINUTES + 1) * 60
        )

        with pytest.raises(TimestampExpiredError):
            validate_launch_params(
                launch_params, TEST_APP_SECRET, FRESHNESS_MINUTES
            )


class TestJwt:
    """Tests for JWT issue/decode."""

    def test_issue_and_decode_roundtrip(self):
        """A freshly issued token decodes to its player_id."""
        token = issue_token("player-uuid-1", ttl_minutes=60)

        assert decode_token(token) == "player-uuid-1"

    def test_expired_token_raises(self):
        """A token past its TTL is rejected."""
        token = issue_token("player-uuid-1", ttl_minutes=-1)

        with pytest.raises(InvalidTokenError):
            decode_token(token)

    def test_tampered_token_raises(self):
        """A token signed with a different secret is rejected."""
        forged = issue_token("player-uuid-1", ttl_minutes=60)
        # Re-sign the same payload with a different secret
        import jwt as pyjwt

        payload = pyjwt.decode(forged, options={"verify_signature": False})
        tampered = pyjwt.encode(payload, "attacker-secret", algorithm="HS256")

        with pytest.raises(InvalidTokenError):
            decode_token(tampered)

    def test_garbage_token_raises(self):
        """A non-JWT string is rejected."""
        with pytest.raises(InvalidTokenError):
            decode_token("not-a-jwt")
