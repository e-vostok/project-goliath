"""
The "wake bell" between producers and the sender task (Spec 3.1).

Producers insert ``bot_outbox`` rows inside their own transaction and
register a one-shot ``after_commit`` hook that calls
:func:`request_wake`; Issue 3's sender installs the ``asyncio.Event``
via :func:`install_wake_event`. Until then the bell is a no-op — the
fallback is the sender's ``poll_interval_seconds`` sweep. Safe to call
from any context: no installed event means nothing happens.
"""

from __future__ import annotations

import asyncio

_wake_event: asyncio.Event | None = None


def install_wake_event(event: asyncio.Event | None) -> None:
    """Install the sender's bell (Issue 3), or clear it on shutdown."""
    global _wake_event
    _wake_event = event


def request_wake() -> None:
    """Ring the bell if one is installed; a no-op otherwise."""
    event = _wake_event
    if event is not None:
        event.set()
