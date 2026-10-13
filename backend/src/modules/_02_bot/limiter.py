"""
Rate limiter of module 02_bot (Spec 3.5) — async token bucket.

Capacity and refill rate are ``sender.max_requests_per_second``: one
``acquire()`` spends one token and waits until the bucket refills.
The monotonic clock and the sleep function are injectable so tests
never touch real time (Anti-Mock Guard).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class TokenBucket:
    """FIFO token bucket shared by every sender coroutine."""

    def __init__(
        self,
        rate: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rate = float(rate)
        self._tokens = float(rate)
        self._updated = clock()
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Spend one token, waiting for the refill when the bucket is dry."""
        async with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(
                    self._rate,
                    self._tokens + self._rate * (now - self._updated),
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Sleeping inside the lock keeps waiters FIFO: each
                # woken coroutine sees the tokens it waited for.
                await self._sleep((1.0 - self._tokens) / self._rate)
