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
from collections.abc import Collection
from urllib.parse import urlsplit

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    AnthemUrlInvalidError,
    CapitalNameInvalidError,
    CoreDomainError,
    DescriptionInvalidError,
    GenderInvalidError,
    HistoryUrlInvalidError,
    LeaderBioInvalidError,
    LeaderNameInvalidError,
    LeaderTitleInvalidError,
    MottoInvalidError,
    ShortNameInvalidError,
    SuccessionInvalidError,
)
from modules._00_core.nation_enums import GENDERS, SUCCESSION_TYPES

# Unicode categories banned from single-line profile text: control
# characters (Cc, incl. newline/tab) and invisible format chars (Cf,
# incl. zero-width spaces).
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf"})

# VK article path: "@", then a slug without slashes or whitespace.
_HISTORY_PATH_RE = re.compile(r"/@[^/\s]+")

# A field validator's error type: a CoreDomainError built from a reason.
_TextError = type[CoreDomainError]


def _validate_text(
    value: str,
    *,
    min_length: int,
    max_length: int,
    error: _TextError,
) -> str:
    """Shared Part 3 rule for the single-line profile text fields."""
    text = value.strip()
    if not (min_length <= len(text) <= max_length):
        raise error(
            f"must be between {min_length} and {max_length} characters, got {len(text)}"
        )
    if any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in text):
        raise error("contains control or formatting characters")
    return text


def _validate_optional_text(
    value: str | None,
    *,
    max_length: int,
    error: _TextError,
) -> str | None:
    """Optional single-line text: empty after strip stores as NULL."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise error(f"must be at most {max_length} characters, got {len(text)}")
    if any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in text):
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


def validate_vk_article_url(
    value: str,
    *,
    max_length: int,
    allowed_hosts: Collection[str],
) -> str:
    """
    The shared VK-article link check (Spec 04_orders, Appendix B1):
    https scheme only, host from ``allowed_hosts`` (lowercased
    compare), no port/userinfo/query/fragment, and the path must be a
    VK article address `/@slug`. Returns the stripped input; raises
    HistoryUrlInvalidError on the first violated rule.
    """
    url = value.strip()
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
    if host is None or host not in allowed_hosts:
        raise HistoryUrlInvalidError("host is not in the allowed list")
    # netloc == hostname rejects credentials, ports and case tricks.
    if parsed.netloc.lower() != host:
        raise HistoryUrlInvalidError("port or userinfo is not allowed")
    if _HISTORY_PATH_RE.fullmatch(parsed.path) is None:
        raise HistoryUrlInvalidError("path must look like '/@article-name'")
    return url


def validate_history_url(value: str, config: CoreConfig) -> str:
    """
    Normalize and check `history_url`; returns the stripped input.

    Part 3 contract — a thin wrapper over :func:`validate_vk_article_url`
    carrying the nation profile's own length limit and host list.
    """
    return validate_vk_article_url(
        value,
        max_length=config.nation.history_url_max_length,
        allowed_hosts=config.nation.history_url_allowed_hosts,
    )


def history_url_allowed_hosts() -> tuple[str, ...]:
    """
    The ``nation.history_url_allowed_hosts`` list of the shipped core
    config — the public read path for satellite modules (Spec
    04_orders, Appendix B1) that validate a VK article link against the
    same allow list without importing ``CoreConfig`` themselves.
    """
    config = CoreConfig.from_yaml(CoreConfig.get_default_config_path())
    return tuple(config.nation.history_url_allowed_hosts)


def validate_short_name(value: str, config: CoreConfig) -> str:
    """Normalize and check `short_name`; returns the value to store."""
    return _validate_text(
        value,
        min_length=config.nation.short_name_min_length,
        max_length=config.nation.short_name_max_length,
        error=ShortNameInvalidError,
    )


def validate_capital_name(value: str, config: CoreConfig) -> str:
    """Normalize and check `capital_name`; returns the value to store."""
    return _validate_text(
        value,
        min_length=config.nation.capital_name_min_length,
        max_length=config.nation.capital_name_max_length,
        error=CapitalNameInvalidError,
    )


def validate_motto(value: str | None, config: CoreConfig) -> str | None:
    """Optional `motto`: normalized text or None (INV-12)."""
    return _validate_optional_text(
        value,
        max_length=config.nation.motto_max_length,
        error=MottoInvalidError,
    )


def validate_description(value: str | None, config: CoreConfig) -> str | None:
    """Optional `description`: normalized text or None (INV-12)."""
    return _validate_optional_text(
        value,
        max_length=config.nation.description_max_length,
        error=DescriptionInvalidError,
    )


def validate_leader_bio(value: str | None, config: CoreConfig) -> str | None:
    """
    Optional multi-line `leader_bio` (Part 3): CR/LF are folded to `\\n`
    first, runs of three or more line breaks collapse to two (at most
    one empty line between paragraphs), then the text is stripped; a
    newline is the only allowed control character. The length limit
    counts the normalized text. Empty after normalization stores NULL.
    """
    if value is None:
        return None
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return None
    max_length = config.nation.leader_bio_max_length
    if len(text) > max_length:
        raise LeaderBioInvalidError(
            f"must be at most {max_length} characters, got {len(text)}"
        )
    if any(
        unicodedata.category(ch) in _FORBIDDEN_CATEGORIES and ch != "\n" for ch in text
    ):
        raise LeaderBioInvalidError("contains control or formatting characters")
    return text


def validate_gender(value: str, config: CoreConfig) -> str:
    """`gender` must be one of ``GENDERS`` (code constants, INV-12)."""
    normalized = value.strip().lower()
    if normalized not in GENDERS:
        raise GenderInvalidError(f"must be one of {list(GENDERS)}, got {value!r}")
    return normalized


def validate_succession_type(value: str, config: CoreConfig) -> str:
    """`succession_type` must be one of ``SUCCESSION_TYPES``."""
    normalized = value.strip().lower()
    if normalized not in SUCCESSION_TYPES:
        raise SuccessionInvalidError(
            f"must be one of {list(SUCCESSION_TYPES)}, got {value!r}"
        )
    return normalized


def validate_anthem_url(value: str | None, config: CoreConfig) -> str | None:
    """
    Optional `anthem_url` (Part 3, soft check): empty stores NULL;
    otherwise https scheme, an allowed host, no port/userinfo and no
    whitespace/control characters. Path, query and fragment are NOT
    checked — the VK music link format is unconfirmed (NAT-0, N4).
    """
    if value is None:
        return None
    url = value.strip()
    if not url:
        return None
    max_length = config.nation.anthem_url_max_length
    if len(url) > max_length:
        raise AnthemUrlInvalidError(
            f"must be at most {max_length} characters, got {len(url)}"
        )
    if any(
        ch.isspace() or unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in url
    ):
        raise AnthemUrlInvalidError("contains whitespace or control characters")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
    except ValueError as exc:
        raise AnthemUrlInvalidError("cannot be parsed") from exc
    if parsed.scheme != "https":
        raise AnthemUrlInvalidError("scheme must be https")
    if host is None or host not in config.nation.anthem_url_allowed_hosts:
        raise AnthemUrlInvalidError("host is not in the allowed list")
    # netloc == hostname rejects credentials, ports and case tricks.
    if parsed.netloc.lower() != host:
        raise AnthemUrlInvalidError("port or userinfo is not allowed")
    return url
