"""
Date formatting of module 03_registry (Spec 3.5).

The game date (``formed``) is rendered by ``format_game_date`` of
module 00_core (``«Месяц Год»``); the real date (``joined``) is
``dd.mm.yyyy`` — e.g. ``"13.10.2026"``, keyed by days since 1970-01-01
of the calendar date in ``tick_timezone``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

_EPOCH = date(1970, 1, 1)


def real_date_parts(created_at: datetime, tick_timezone: str) -> tuple[str, int]:
    """
    The ``joined`` cell values for a stored ``created_at`` (Spec 3.5):
    the display text and the key = days since 1970-01-01 of the calendar
    date in ``tick_timezone``. Naive datetimes are read as UTC (storage
    convention; SQLite returns them naive for ``timezone=True`` columns).
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    local_date = created_at.astimezone(ZoneInfo(tick_timezone)).date()
    text = f"{local_date.day:02d}.{local_date.month:02d}.{local_date.year}"
    return text, (local_date - _EPOCH).days
