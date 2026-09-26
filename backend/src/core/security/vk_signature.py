"""
VK Mini App launch-params signature validation.

Implements the VK signature scheme: all `vk_*` query params are sorted,
URL-encoded into a `key=value&key=value` string, signed with HMAC-SHA256
keyed by the app secret, and base64url-encoded without padding. The
`vk_ts` freshness window guards against replay attacks and clock skew.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

from core.security import SecurityError


class InvalidSignatureError(SecurityError):
    """Raised when the launch-params signature does not match."""

    def __init__(self):
        super().__init__(
            "Launch params signature is invalid",
            "INVALID_SIGNATURE",
        )


class TimestampExpiredError(SecurityError):
    """Raised when vk_ts falls outside the allowed freshness window."""

    def __init__(self):
        super().__init__(
            "Launch params timestamp is outside the freshness window",
            "TIMESTAMP_EXPIRED",
        )


def validate_launch_params(
    raw_query_string: str,
    app_secret: str,
    freshness_minutes: int,
) -> int:
    """
    Validate VK launch params and return the authenticated vk_user_id.

    Args:
        raw_query_string: The raw query string from the Mini App URL
            (e.g. "vk_user_id=1&vk_app_id=2&vk_ts=...&sign=...").
        app_secret: The VK app secret key.
        freshness_minutes: Allowed |now - vk_ts| window, in minutes.

    Returns:
        The vk_user_id extracted from the validated params.

    Raises:
        InvalidSignatureError: If the signature is missing or mismatched,
            or required vk_* params are absent/malformed.
        TimestampExpiredError: If vk_ts is outside the freshness window.
    """
    params = dict(urllib.parse.parse_qsl(raw_query_string, keep_blank_values=True))

    vk_params = sorted(
        (key, value) for key, value in params.items() if key.startswith("vk_")
    )
    base_string = urllib.parse.urlencode(vk_params)

    digest = hmac.new(
        app_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_sign = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    provided_sign = params.get("sign", "")
    if not provided_sign or not hmac.compare_digest(expected_sign, provided_sign):
        raise InvalidSignatureError()

    try:
        vk_ts = int(params["vk_ts"])
        vk_user_id = int(params["vk_user_id"])
    except (KeyError, ValueError):
        raise InvalidSignatureError() from None

    if abs(int(time.time()) - vk_ts) > freshness_minutes * 60:
        raise TimestampExpiredError()

    return vk_user_id
