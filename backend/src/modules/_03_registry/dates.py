"""
Date formatting of module 03_registry (Spec 3.5).

Month names come from a fixed table in code — never from the OS locale —
so the rendered text is identical on every machine. Two formats exist:

- game date (``formed``): ``"{день} {месяц} {год} г."`` — e.g.
  ``"8 января 1 г."``, the year without leading zeros;
- real date (``joined``): ``"{день} {месяц} {год}"`` — e.g.
  ``"13 октября 2026"``, keyed by days since 1970-01-01 of the
  calendar date in ``tick_timezone``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Месяцы в родительном падеже (1..12) — Spec 3.5.
_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_EPOCH = date(1970, 1, 1)


def game_date_text(d: date) -> str:
    """``"8 января 1 г."`` — the game-calendar display text."""
    return f"{d.day} {_MONTHS_GENITIVE[d.month - 1]} {d.year} г."


def real_date_parts(
    created_at: datetime, tick_timezone: str
) -> tuple[str, int]:
    """
    The ``joined`` cell values for a stored ``created_at`` (Spec 3.5):
    the display text and the key = days since 1970-01-01 of the calendar
    date in ``tick_timezone``. Naive datetimes are read as UTC (storage
    convention; SQLite returns them naive for ``timezone=True`` columns).
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    local_date = created_at.astimezone(ZoneInfo(tick_timezone)).date()
    text = (
        f"{local_date.day} {_MONTHS_GENITIVE[local_date.month - 1]} "
        f"{local_date.year}"
    )
    return text, (local_date - _EPOCH).days
