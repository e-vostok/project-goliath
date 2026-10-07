"""
Circuit breaker of module 02_bot (Spec 3.5) — CLOSED -> OPEN ->
HALF_OPEN.

A sliding ``breaker.window_seconds`` window holds the counted send
results (n attempts, f failures). The breaker opens when
``n >= min_attempts`` and ``f/n >= failure_ratio``, stays OPEN for
``breaker.open_seconds``, then admits exactly one probe in HALF_OPEN:
success closes the breaker and clears the window, failure re-opens it.

In-memory per process (Spec: resets on restart); the monotonic clock
is injectable so tests never sleep.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from enum import Enum

from modules._02_bot.config_schema import BreakerSettings


class BreakerState(str, Enum):
    """Circuit breaker states (Spec 3.5)."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """In-memory sliding-window breaker for the VK send path."""

    def __init__(
        self,
        settings: BreakerSettings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._window_seconds = settings.window_seconds
        self._min_attempts = settings.min_attempts
        self._failure_ratio = settings.failure_ratio
        self._open_seconds = settings.open_seconds
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0
        self._probe_in_flight = False
        self._window: deque[tuple[float, bool]] = deque()

    @property
    def state(self) -> BreakerState:
        """Current state; an expired OPEN window advances to HALF_OPEN."""
        if (
            self._state == BreakerState.OPEN
            and self._clock() - self._opened_at >= self._open_seconds
        ):
            self._state = BreakerState.HALF_OPEN
            self._probe_in_flight = False
        return self._state

    def allow(self) -> bool:
        """
        Whether one send may proceed: always in CLOSED, never in OPEN,
        and exactly once (the probe) in HALF_OPEN.
        """
        state = self.state
        if state == BreakerState.CLOSED:
            return True
        if state == BreakerState.OPEN:
            return False
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record(self, success: bool, counts: bool) -> None:
        """
        Fold one send result into the window.

        ``success`` is what the probe cares about (VK answered at all);
        ``counts`` is the Spec-2.7 flag — uncounted classes neither
        grow n nor f and are ignored while CLOSED.
        """
        now = self._clock()
        if self._state == BreakerState.HALF_OPEN:
            # Only the probe's own record resolves HALF_OPEN.
            if not self._probe_in_flight:
                return
            self._probe_in_flight = False
            if success:
                self._state = BreakerState.CLOSED
                self._window.clear()
            else:
                self._state = BreakerState.OPEN
                self._opened_at = now
            return
        if self._state != BreakerState.CLOSED or not counts:
            return
        while (
            self._window
            and now - self._window[0][0] > self._window_seconds
        ):
            self._window.popleft()
        self._window.append((now, not success))
        n = len(self._window)
        failures = sum(1 for _, failed in self._window if failed)
        if n >= self._min_attempts and failures / n >= self._failure_ratio:
            self._state = BreakerState.OPEN
            self._opened_at = now
