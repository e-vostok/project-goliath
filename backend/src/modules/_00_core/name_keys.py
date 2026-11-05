"""
Uniqueness keys for nation and application names (0.14.0 unit 3b).

``name_key`` turns a displayed name into the value the uniqueness
checks compare: «Рим», «РИМ» and «рим» share one key, and «Берёза»
equals «Береза». Names are still stored and shown exactly as the
player typed them — only the comparison changes.

The key is computed in Python, never in SQL: SQLite ``lower()`` folds
ASCII only and would leave Cyrillic case pairs distinct. Dependency-
free by design so both the ORM ``@validates`` hooks and migration 0021
(which carries an inlined copy — migrations must not import
application code) share the same definition.
"""

from __future__ import annotations

import unicodedata


def name_key(value: str) -> str:
    """The canonical uniqueness key of a displayed name.

    Unicode NFKC first (compatibility characters fold to their normal
    form), then strip and collapse every whitespace run to one space,
    then ``casefold()`` (the full Unicode fold — «ё» survives it), and
    finally «ё» maps to «е».
    """
    normalized = unicodedata.normalize("NFKC", value)
    collapsed = " ".join(normalized.split())
    return collapsed.casefold().replace("ё", "е")
