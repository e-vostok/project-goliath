"""
In-process liveness heartbeat for the tick scheduler.

The scheduler loop calls touch() every time it wakes and after every
handled error, so a wedged or dead loop shows up as a growing
age_seconds(). DEP-4's /api/v1/health reads this; there is deliberately
no storage and no locking — a single-process stamp, good enough to
answer "is the loop alive".
"""

from __future__ import annotations

from datetime import datetime, timezone

_last_beat_at: datetime | None = None


def touch() -> None:
    """Stamp the heartbeat with now (UTC)."""
    global _last_beat_at
    _last_beat_at = datetime.now(timezone.utc)


def last_beat_at() -> datetime | None:
    """The last touch() instant, or None if the loop never woke."""
    return _last_beat_at


def age_seconds() -> float | None:
    """Seconds since the last touch(), or None if never touched."""
    if _last_beat_at is None:
        return None
    return (datetime.now(timezone.utc) - _last_beat_at).total_seconds()
