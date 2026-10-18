"""
Ready-made flag/portrait catalog URL helpers (Spec Part 1).

The only place that knows how a catalog identifier becomes an asset
address (INV-16): ``flag_url``/``portrait_url`` map ``<id>`` to the
static path served from ``frontend/public/assets/nations/``; ``None``
maps to ``None`` (nations without a chosen picture, and every pre-0.8.0
nation). Membership in ``catalog.flag_ids``/``catalog.portrait_ids`` is
checked at validation time; file existence is a CI concern (INV-15).
"""

from __future__ import annotations

_FLAGS_DIR = "/assets/nations/flags"
_PORTRAITS_DIR = "/assets/nations/portraits"


def flag_url(flag_id: str | None) -> str | None:
    """Static URL of the catalog flag, or None when no flag is set."""
    if flag_id is None:
        return None
    return f"{_FLAGS_DIR}/{flag_id}.png"


def portrait_url(portrait_id: str | None) -> str | None:
    """Static URL of the catalog portrait, or None when none is set."""
    if portrait_id is None:
        return None
    return f"{_PORTRAITS_DIR}/{portrait_id}.png"
