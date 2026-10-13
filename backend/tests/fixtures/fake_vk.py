"""
FakeVk — the VK HTTP boundary for the 02_bot suite (Anti-Mock Guard).

The ONLY thing tests substitute is the external VK API: an
``httpx.MockTransport`` driven by a queue of scripted responses. The
database stays real.

Each ``push`` item may be:

- ``httpx.Response`` — returned as-is;
- ``Exception`` — raised (e.g. ``httpx.ReadTimeout``);
- ``Callable[[httpx.Request], httpx.Response]`` — full control.

When the queue is empty the last response repeats, so a single
``respond_send_ok()`` covers an open-ended send loop. ``requests``
records every call (method, form fields, headers) for assertions.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qs

import httpx


class FakeVk:
    """Scriptable VK API double behind ``httpx.MockTransport``."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._queue: deque = deque()
        self._last: httpx.Response | Callable | None = None
        self.transport = httpx.MockTransport(self._handle)

    # -- scripting -----------------------------------------------------

    def push(self, *items) -> None:
        """Append scripted responses/exceptions/handlers to the queue."""
        self._queue.extend(items)

    def respond_json(self, body, status: int = 200) -> None:
        self.push(httpx.Response(status, json=body))

    def respond_send_ok(self, message_id: int = 1, peer_id: int = 0) -> None:
        """A well-formed messages.send success (``response[0]``)."""
        self.respond_json(
            {"response": [{"peer_id": peer_id, "message_id": message_id}]}
        )

    def respond_call_error(self, code: int) -> None:
        """A top-level VK call error (``error.error_code``)."""
        self.respond_json(
            {"error": {"error_code": code, "error_msg": "fake error"}}
        )

    def respond_recipient_error(self, code: int) -> None:
        """A per-recipient error (``response[0].error.code``)."""
        self.respond_json(
            {
                "response": [
                    {
                        "peer_id": 0,
                        "error": {"code": code, "description": "fake"},
                    }
                ]
            }
        )

    def respond_allowed(self, allowed: bool) -> None:
        """isMessagesFromGroupAllowed answer (``is_allowed`` 1/0)."""
        self.respond_json({"response": {"is_allowed": 1 if allowed else 0}})

    def respond_raw(self, content: bytes | str, status: int = 200) -> None:
        """A non-JSON or arbitrary body (parse failure path)."""
        if isinstance(content, str):
            content = content.encode()
        self.push(httpx.Response(status, content=content))

    def fail_timeout(self) -> None:
        self.push(httpx.ReadTimeout("simulated vk timeout"))

    def fail_connect(self) -> None:
        self.push(httpx.ConnectError("simulated vk connect error"))

    # -- inspection ------------------------------------------------------

    def send_requests(self) -> list[httpx.Request]:
        """Calls to ``messages.send`` only."""
        return [r for r in self.requests if r.url.path.endswith("messages.send")]

    def last_form(self) -> dict[str, str]:
        """The urlencoded form fields of the most recent request."""
        assert self.requests, "FakeVk saw no requests"
        parsed = parse_qs(self.requests[-1].content.decode())
        return {key: values[0] for key, values in parsed.items()}

    # -- transport -------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._queue:
            item = self._queue.popleft()
            if not isinstance(item, Exception):
                self._last = item
        else:
            item = self._last or httpx.Response(
                200,
                json={"response": [{"peer_id": 0, "message_id": 1}]},
            )
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item


def form_keyboard(request: httpx.Request) -> dict | None:
    """Decode the ``keyboard`` JSON param of a send request, if sent."""
    form = parse_qs(request.content.decode())
    raw = form.get("keyboard", [None])[0]
    return json.loads(raw) if raw else None
