"""
Pure validation rules for the nation profile fields (Spec Part 3).

No DB access and no state: each function takes the raw input plus the
loaded CoreConfig, returns the normalized value to store (text fields —
after strip(); history URL — stripped but otherwise untouched), and
raises the matching domain error on the first violated rule. The service
layer is the single place that calls these (INV-9); DTOs only type the
fields.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    HistoryUrlInvalidError,
    LeaderNameInvalidError,
    LeaderTitleInvalidError,
)

# Unicode categories banned from single-line profile text: control
# characters (Cc, incl. newline/tab) and invisible format chars (Cf,
# incl. zero-width spaces).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf"})

# VK article path: "@", then a slug without slashes or whitespace.
_HISTORY_PATH_RE = re.compile(r"/@[^/\s]+")


def _validate_text(
    value: str,
    *,
    min_length: int,
    max_length: int,
    error: type[LeaderNameInvalidError] | type[LeaderTitleInvalidError],
) -> str:
    """Shared Part 3 rule for the single-line profile text fields."""
    text = value.strip()
    if not (min_length <= len(text) <= max_length):
        raise error(
            f"must be between {min_length} and {max_length} characters, "
            f"got {len(text)}"
        )
    if any(
        unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in text
    ):
        raise error("contains control or formatting characters")
    return text


def validate_leader_name(value: str, config: CoreConfig) -> str:
    """Normalize and check `leader_name`; returns the value to store."""
    return _validate_text(
        value,
        min_length=config.nation.leader_name_min_length,
        max_length=config.nation.leader_name_max_length,
        error=LeaderNameInvalidError,
    )


def validate_leader_title(value: str, config: CoreConfig) -> str:
    """Normalize and check `leader_title`; returns the value to store."""
    return _validate_text(
        value,
        min_length=config.nation.leader_title_min_length,
        max_length=config.nation.leader_title_max_length,
        error=LeaderTitleInvalidError,
    )


def validate_history_url(value: str, config: CoreConfig) -> str:
    """
    Normalize and check `history_url`; returns the stripped input.

    Part 3 contract: https scheme only, host from the configured allow
    list (lowercased compare), no port/userinfo/query/fragment, and the
    path must be a VK article address `/@slug`.
    """
    url = value.strip()
    max_length = config.nation.history_url_max_length
    if len(url) > max_length:
        raise HistoryUrlInvalidError(
            f"must be at most {max_length} characters, got {len(url)}"
        )
    if any(
        ch.isspace()
        or unicodedata.category(ch) in _FORBIDDEN_CATEGORIES
        or ch in "\\?#"
        for ch in url
    ):
        raise HistoryUrlInvalidError(
            "contains whitespace, control characters or one of '\\?#'"
        )
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError as exc:
        raise HistoryUrlInvalidError("cannot be parsed") from exc
    if parsed.scheme != "https":
        raise HistoryUrlInvalidError("scheme must be https")
    if host is None or host not in config.nation.history_url_allowed_hosts:
        raise HistoryUrlInvalidError("host is not in the allowed list")
    # netloc == hostname rejects credentials, ports and case tricks.
    if parsed.netloc.lower() != host:
        raise HistoryUrlInvalidError("port or userinfo is not allowed")
    if _HISTORY_PATH_RE.fullmatch(parsed.path) is None:
        raise HistoryUrlInvalidError("path must look like '/@article-name'")
    return url
