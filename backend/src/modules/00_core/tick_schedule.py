"""
Daily fixed-local-time tick scheduling for module 00_core.

The game ticks once per day at tick.tick_time (strict "HH:MM", 24h) in
tick.tick_timezone — not "every N hours". next_tick_after() computes the
next occurrence of that wall-clock time strictly after a given instant
and returns it as a tz-aware UTC datetime for game_clock.next_tick_at.

The next occurrence is resolved per local calendar date (today's tick
time, else tomorrow's), never as now + 24h, so DST shifts move the UTC
instant while the local time stays fixed.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TICK_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def next_tick_after(now: datetime, tick_time: str, tz_name: str) -> datetime:
    """
    Next occurrence of tick_time in tz_name strictly after now, in UTC.

    Args:
        now: tz-aware reference instant (naive raises ValueError).
        tick_time: local wall-clock time, strict "HH:MM" 24-hour format.
        tz_name: IANA zone name resolvable via zoneinfo.ZoneInfo.

    Returns:
        The tz-aware UTC datetime of the next local tick_time.
    """
    if now.tzinfo is None:
        raise ValueError("next_tick_after() requires a tz-aware `now`")
    if TICK_TIME_PATTERN.match(tick_time) is None:
        raise ValueError(
            f"tick_time must be strict 24h 'HH:MM', got {tick_time!r}"
        )

    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz)
    hour, minute = (int(part) for part in tick_time.split(":"))

    candidate = datetime.combine(
        local_now.date(), time(hour, minute), tzinfo=tz
    )
    if candidate <= local_now:
        candidate = datetime.combine(
            local_now.date() + timedelta(days=1), time(hour, minute),
            tzinfo=tz,
        )
    return candidate.astimezone(timezone.utc)


def format_game_time(value: datetime | None, tz_name: str) -> str | None:
    """
    Render an instant as 'YYYY-MM-DD HH:MM:SS' in the named zone.

    Shared display formatting for admin JSON output: a plain game-local
    wall-clock string — whole seconds, no offset suffix, no 'T'. Storage
    stays tz-aware UTC; this is presentation only.

    Args:
        value: the instant to render; naive datetimes are read as UTC
            (SQLite returns naive values even for tz-aware writes).
            None stays None.
        tz_name: IANA zone name resolvable via zoneinfo.ZoneInfo —
            callers pass tick.tick_timezone.

    Returns:
        value.astimezone(zone).strftime('%Y-%m-%d %H:%M:%S'), or None.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")
