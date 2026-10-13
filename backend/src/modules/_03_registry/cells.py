"""
Cell constructors of module 03_registry (Spec 3.6, Appendix A).

Every cell is a plain JSON-able value. ``cell_matches`` is the reverse
check: ``build_table`` runs it on every cell of every configured column
and turns a violation into ``REGISTRY_PROVIDER_FAILED`` — a source that
returns a wrong shape can never leak malformed JSON to the client.
"""

from __future__ import annotations

import re

from modules._03_registry.registry import Cell

_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def cell_date(text: str, key: int) -> dict:
    """``date`` cell: display text plus the numeric sort/filter key."""
    return {"text": text, "key": key}


def cell_person(
    name: str, avatar_url: str | None, is_fallback: bool
) -> dict:
    """``person`` cell: name (never empty, INV-R7), avatar, fallback flag."""
    return {
        "name": name,
        "avatar_url": avatar_url,
        "is_fallback": is_fallback,
    }


def cell_flag(color: str, image_url: str | None) -> dict:
    """``flag`` cell: a colour square or an uploaded flag image."""
    return {"color": color, "image_url": image_url}


def cell_nation(name: str, color: str) -> dict:
    """``nation`` cell: a colour mark and the nation's name."""
    return {"name": name, "color": color}


def _is_int(value: object) -> bool:
    """Strict int check — ``bool`` is an int subclass but not a cell int."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_dict_exact(
    value: object, keys: frozenset[str]
) -> dict | None:
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
        return (
            d is not None
            and isinstance(d["text"], str)
            and _is_int(d["key"])
        )
    if column_type == "person":
        d = _is_dict_exact(
            cell, frozenset({"name", "avatar_url", "is_fallback"})
        )
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
        d = _is_dict_exact(cell, frozenset({"name", "color"}))
        return (
            d is not None
            and isinstance(d["name"], str)
            and isinstance(d["color"], str)
            and _COLOR_RE.fullmatch(d["color"]) is not None
        )
    return False
