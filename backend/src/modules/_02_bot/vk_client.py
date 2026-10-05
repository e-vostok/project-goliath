"""
VK API client of module 02_bot (Spec 3.3, V3/V4/V12/V14).

One ``httpx.AsyncClient`` with ``base_url = vk.api_base_url`` and the
``vk.http_timeout_seconds`` timeout. The community key travels ONLY in
the ``Authorization: Bearer`` header (INV-B9): never in the URL, the
form body, logs, exceptions or ``repr``. Log lines name the method,
the HTTP status and the VK error code — request and response bodies
are never logged.

Response parsing follows Spec 3.3 exactly: a top-level ``error``
object is a call error (``error.error_code``); otherwise ``response``
must be a non-empty list and ``response[0]`` decides — ``message_id``
without ``error`` is a success, an ``error`` object
``{code, description}`` is a recipient error, and every other shape
(empty list, neither field, not JSON, HTTP 5xx, timeout, connection
error) is a transport failure. ``SendOutcome.code`` is 0 for transport.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import httpx

from modules._02_bot.config_schema import BotConfig

logger = logging.getLogger(__name__)


class SendKind(str, Enum):
    """What the VK boundary answered for one messages.send."""

    OK = "OK"                  # response[0].message_id, no error
    ERROR = "ERROR"            # call-level or recipient error code
    TRANSPORT = "TRANSPORT"    # no parseable answer at all


@dataclass(frozen=True)
class SendOutcome:
    """One send attempt's result; ``code`` is 0 for TRANSPORT."""

    kind: SendKind
    message_id: int | None = None
    code: int = 0


class VkClient:
    """Thin async wrapper over the VK methods the sender needs."""

    def __init__(
        self,
        config: BotConfig,
        token: str,
        group_id: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._group_id = group_id
        self._api_version = config.vk.api_version
        self._client = httpx.AsyncClient(
            base_url=config.vk.api_base_url,
            timeout=httpx.Timeout(config.vk.http_timeout_seconds),
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
        )

    async def _call(self, method: str, data: dict[str, str]) -> httpx.Response | None:
        """
        One POST ``application/x-www-form-urlencoded`` call.

        Returns the response on any transportable answer (the body may
        still be an error envelope); ``None`` when nothing parseable
        could arrive — timeout, connection error, HTTP 5xx.
        """
        data = {**data, "v": self._api_version}
        try:
            response = await self._client.post(f"/{method}", data=data)
        except httpx.HTTPError as exc:
            logger.warning(
                "vk call %s failed: transport error (%s)",
                method,
                type(exc).__name__,
            )
            return None
        if response.status_code >= 500:
            logger.warning(
                "vk call %s failed: HTTP %s", method, response.status_code
            )
            return None
        return response

    async def send_message(
        self,
        peer_id: int,
        random_id: int,
        message: str,
        keyboard_json: str | None = None,
    ) -> SendOutcome:
        """
        ``messages.send`` to one peer (Spec 3.3 step 3).

        ``peer_ids``/``random_id``/``message``/``keyboard`` (when a
        keyboard goes along) plus the constant ``disable_mentions=1``
        and ``dont_parse_links=1``; no ``intent`` (V6).
        """
        data = {
            "peer_ids": str(peer_id),
            "random_id": str(random_id),
            "message": message,
            "disable_mentions": "1",
            "dont_parse_links": "1",
        }
        if keyboard_json is not None:
            data["keyboard"] = keyboard_json

        response = await self._call("messages.send", data)
        if response is None:
            return SendOutcome(SendKind.TRANSPORT)
        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "messages.send failed: non-JSON body (HTTP %s)",
                response.status_code,
            )
            return SendOutcome(SendKind.TRANSPORT)
        if not isinstance(body, dict):
            return SendOutcome(SendKind.TRANSPORT)

        call_error = body.get("error")
        if call_error is not None:
            code = (
                call_error.get("error_code")
                if isinstance(call_error, dict)
                else None
            )
            if not isinstance(code, int):
                return SendOutcome(SendKind.TRANSPORT)
            logger.warning("messages.send call error: code %s", code)
            return SendOutcome(SendKind.ERROR, code=code)

        entries = body.get("response")
        if not isinstance(entries, list) or not entries:
            return SendOutcome(SendKind.TRANSPORT)
        first = entries[0]
        if not isinstance(first, dict):
            return SendOutcome(SendKind.TRANSPORT)

        recipient_error = first.get("error")
        if recipient_error is not None:
            code = (
                recipient_error.get("code")
                if isinstance(recipient_error, dict)
                else None
            )
            if not isinstance(code, int):
                return SendOutcome(SendKind.TRANSPORT)
            logger.warning(
                "messages.send recipient error: code %s", code
            )
            return SendOutcome(SendKind.ERROR, code=code)

        message_id = first.get("message_id")
        if isinstance(message_id, int):
            return SendOutcome(SendKind.OK, message_id=message_id)
        return SendOutcome(SendKind.TRANSPORT)

    async def is_messages_from_group_allowed(
        self, group_id: int, user_id: int
    ) -> bool | None:
        """
        ``messages.isMessagesFromGroupAllowed``: True/False from
        ``response.is_allowed`` (1/0); None on any error or malformed
        answer — a failed check changes nothing (Spec 3.7).
        """
        response = await self._call(
            "messages.isMessagesFromGroupAllowed",
            {"group_id": str(group_id), "user_id": str(user_id)},
        )
        if response is None:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        payload = body.get("response")
        if not isinstance(payload, dict):
            return None
        is_allowed = payload.get("is_allowed")
        if is_allowed in (0, 1):
            return is_allowed == 1
        return None

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
