"""
Cell constructors of module 03_registry (Spec 3.6, Appendix A).

Every cell is a plain JSON-able value. ``cell_matches`` is the reverse
check: ``build_table`` runs it on every cell of every configured column
and turns a violation into ``REGISTRY_PROVIDER_FAILED`` — a source that
returns a wrong shape can never leak malformed JSON to the client.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from modules._03_registry.registry import Cell

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_EPOCH = date(1970, 1, 1)


def cell_date(text: str, key: int) -> dict:
    """``date`` cell: display text plus the numeric sort/filter key."""
    return {"text": text, "key": key}


def cell_datetime(moment: datetime | None, tz: str, mark: str | None = None) -> dict:
    """
    ``datetime`` cell (Spec 04_orders, Appendix A): ``date``/``time``
    display lines in ``tz``, ``key`` — Unix seconds for sorting,
    ``day`` — whole days since 1970-01-01 in ``tz`` for ``date_range``;
    ``mark`` is ``None`` or ``"overdue"``. A ``None`` moment gives an
    empty cell (all-null date/time/key/day) that keeps ``mark`` — an
    overdue stage without a timestamp still shows the mark. Naive
    datetimes are read as UTC (storage convention).
    """
    if moment is None:
        return {
            "date": None,
            "time": None,
            "key": None,
            "day": None,
            "mark": mark,
        }
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(ZoneInfo(tz))
    return {
        "date": f"{local.day:02d}.{local.month:02d}.{local.year}",
        "time": f"{local.hour:02d}:{local.minute:02d}",
        "key": int(moment.timestamp()),
        "day": (local.date() - _EPOCH).days,
        "mark": mark,
    }


def cell_action_text(text: str, action: str) -> dict:
    """``action_text`` cell: clickable text; ``action`` is
    ``<handler>:<arg>`` — the client calls the registered handler."""
    return {"text": text, "action": action}


def cell_person(name: str, avatar_url: str | None, is_fallback: bool) -> dict:
    """``person`` cell: name (never empty, INV-R7), avatar, fallback flag."""
    return {
        "name": name,
        "avatar_url": avatar_url,
        "is_fallback": is_fallback,
    }


def cell_flag(color: str, image_url: str | None) -> dict:
    """``flag`` cell: a colour square or an uploaded flag image."""
    return {"color": color, "image_url": image_url}


def cell_nation(name: str, color: str, flag_url: str | None = None) -> dict:
    """``nation`` cell: colour mark and name; ``flag_url`` is the nation's
    uploaded flag image (``None`` — the colour mark stands in for it)."""
    return {"name": name, "color": color, "flag_url": flag_url}


def _is_int(value: object) -> bool:
    """Strict int check — ``bool`` is an int subclass but not a cell int."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_dict_exact(value: object, keys: frozenset[str]) -> dict | None:
    """The value as a dict with exactly ``keys``, else None."""
    if not isinstance(value, dict) or set(value.keys()) != keys:
        return None
    return value


def cell_matches(column_type: str, cell: Cell) -> bool:
    """
    True when ``cell`` satisfies the Spec 3.6 shape of ``column_type``.

    ``person`` and ``flag`` are never null (INV-R7: a person cell always
    carries a non-empty name); the other types may be ``None``. A missing
    value key in ``row.cells`` is reported by the caller as the same
    failure — ``row.cells.get(col.source)`` returning ``None`` for a
    non-nullable type fails here too.
    """
    if cell is None:
        return column_type not in ("person", "flag")
    if column_type in ("index", "integer", "gauge"):
        return _is_int(cell)
    if column_type == "text":
        return isinstance(cell, str)
    if column_type == "date":
        d = _is_dict_exact(cell, frozenset({"text", "key"}))
        return d is not None and isinstance(d["text"], str) and _is_int(d["key"])
    if column_type == "datetime":
        d = _is_dict_exact(cell, frozenset({"date", "time", "key", "day", "mark"}))
        if d is None or d["mark"] not in (None, "overdue"):
            return False
        filled = (d["date"], d["time"], d["key"], d["day"])
        if all(v is None for v in filled):
            return True
        return (
            isinstance(d["date"], str)
            and isinstance(d["time"], str)
            and _is_int(d["key"])
            and _is_int(d["day"])
        )
    if column_type == "action_text":
        d = _is_dict_exact(cell, frozenset({"text", "action"}))
        return (
            d is not None
            and isinstance(d["text"], str)
            and isinstance(d["action"], str)
        )
    if column_type == "person":
        d = _is_dict_exact(cell, frozenset({"name", "avatar_url", "is_fallback"}))
        return (
            d is not None
            and isinstance(d["name"], str)
            and len(d["name"]) > 0
            and (d["avatar_url"] is None or isinstance(d["avatar_url"], str))
            and isinstance(d["is_fallback"], bool)
        )
    if column_type == "flag":
        d = _is_dict_exact(cell, frozenset({"color", "image_url"}))
        return (
            d is not None
            and isinstance(d["color"], str)
            and _COLOR_RE.fullmatch(d["color"]) is not None
            and (d["image_url"] is None or isinstance(d["image_url"], str))
        )
    if column_type == "nation":
        d = _is_dict_exact(cell, frozenset({"name", "color", "flag_url"}))
        return (
            d is not None
            and isinstance(d["name"], str)
            and isinstance(d["color"], str)
            and _COLOR_RE.fullmatch(d["color"]) is not None
            and (d["flag_url"] is None or isinstance(d["flag_url"], str))
        )
    return False
