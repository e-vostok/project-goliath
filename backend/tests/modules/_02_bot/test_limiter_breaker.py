"""
Tests for the token bucket and circuit breaker (Spec 3.5, T11).

Clocks and sleeps are injected — no real time passes. The bucket
never exceeds its rate, and the breaker walks
CLOSED -> OPEN -> HALF_OPEN -> CLOSED (and back to OPEN on a failed
probe).
"""

from __future__ import annotations

import pytest

from modules._02_bot.breaker import BreakerState, CircuitBreaker
from modules._02_bot.config_schema import BreakerSettings
from modules._02_bot.limiter import TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _breaker(**kw) -> CircuitBreaker:
    settings = BreakerSettings(
        window_seconds=kw.pop("window_seconds", 60),
        min_attempts=kw.pop("min_attempts", 3),
        failure_ratio=kw.pop("failure_ratio", 0.5),
        open_seconds=kw.pop("open_seconds", 30),
    )
    return CircuitBreaker(settings, clock=kw.pop("clock"))


class TestTokenBucket:
    async def test_rate_never_exceeded(self):
        """10 acquires at rate 5: 5 instant, then 5 waits of 0.2s."""
        clock = FakeClock()
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)
            clock.advance(seconds)

        bucket = TokenBucket(5, clock=clock, sleep=fake_sleep)
        for _ in range(10):
            await bucket.acquire()

        assert len(slept) == 5
        assert slept == pytest.approx([0.2] * 5)
        assert clock.t == pytest.approx(1.0)

    async def test_refill_after_idle(self):
        """A full bucket refills while idle."""
        clock = FakeClock()

        async def fail_sleep(seconds: float) -> None:
            raise AssertionError("acquire slept on a refilled bucket")

        bucket = TokenBucket(2, clock=clock, sleep=fail_sleep)
        await bucket.acquire()
        await bucket.acquire()
        clock.advance(10.0)
        # Both tokens are back — no wait needed.
        await bucket.acquire()
        await bucket.acquire()


class TestCircuitBreaker:
    def test_closed_open_half_open_closed(self):
        clock = FakeClock()
        breaker = _breaker(clock=clock)
        assert breaker.allow() is True

        # 3 counted failures in a row: n=3 >= 3, f/n = 1 >= 0.5.
        for _ in range(3):
            breaker.record(success=False, counts=True)
        assert breaker.state == BreakerState.OPEN
        assert breaker.allow() is False

        # Still open inside open_seconds.
        clock.advance(29)
        assert breaker.allow() is False
        clock.advance(1)
        # HALF_OPEN: one probe, second caller refused.
        assert breaker.allow() is True
        assert breaker.allow() is False
        breaker.record(success=True, counts=True)
        assert breaker.state == BreakerState.CLOSED
        assert breaker.allow() is True

    def test_failed_probe_reopens(self):
        clock = FakeClock()
        breaker = _breaker(clock=clock)
        for _ in range(3):
            breaker.record(success=False, counts=True)
        clock.advance(30)
        assert breaker.allow() is True  # the probe
        breaker.record(success=False, counts=True)
        assert breaker.state == BreakerState.OPEN
        assert breaker.allow() is False

    def test_ratio_and_window(self):
        """Successes dilute the ratio; old entries fall off the window."""
        clock = FakeClock()
        breaker = _breaker(clock=clock, min_attempts=4, failure_ratio=0.5)
        breaker.record(success=False, counts=True)
        breaker.record(success=True, counts=True)
        breaker.record(success=False, counts=True)
        breaker.record(success=True, counts=True)
        # n=4, f=2, ratio 0.5 >= 0.5 -> open.
        assert breaker.state == BreakerState.OPEN

        breaker2 = _breaker(clock=clock, min_attempts=4, failure_ratio=0.6)
        breaker2.record(success=False, counts=True)
        breaker2.record(success=True, counts=True)
        breaker2.record(success=False, counts=True)
        breaker2.record(success=True, counts=True)
        assert breaker2.state == BreakerState.CLOSED

    def test_uncounted_results_do_not_open(self):
        clock = FakeClock()
        breaker = _breaker(clock=clock)
        for _ in range(10):
            breaker.record(success=False, counts=False)
        assert breaker.state == BreakerState.CLOSED
