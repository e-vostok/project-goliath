"""
VK error classification of module 02_bot (Spec 2.7).

Every send outcome — a call-level ``error.error_code``, a recipient
``response[0].error.code``, or a transport failure — folds into one
:class:`ErrorClass`, and each class has a fixed action in the sender
plus a "counts toward the circuit breaker" flag (Spec 3.5: only the
classes the table marks as counted feed the failure ratio).

``TRANSPORT`` is not a VK code: the client reports network failures,
timeouts, HTTP 5xx and unrecognised bodies under code ``0``, which
classifies here so the sender's switch stays total.
"""

from __future__ import annotations

from enum import Enum


class ErrorClass(str, Enum):
    """Failure class of one send attempt (Spec 2.7)."""

    SYSTEM = "SYSTEM"                    # 1, 10 — retry, counts
    RATE_GLOBAL = "RATE_GLOBAL"          # 6, 29 — sender-wide pause, counts
    FLOOD_PLAYER = "FLOOD_PLAYER"        # 9 — per-player delay, no count
    SPAM_RESTRICTED = "SPAM_RESTRICTED"  # 984 — retry + CRITICAL, counts
    CONSENT_LOST = "CONSENT_LOST"        # 900, 901, 902, 1021 — drop
    AUTH = "AUTH"                        # 5, 7, 15, 27, 28 — HALTED_AUTH
    BAD_REQUEST = "BAD_REQUEST"          # 100, 911 — drop, counts
    TOO_LONG = "TOO_LONG"                # 914 — drop, no count
    UNKNOWN = "UNKNOWN"                  # any other code — retry, counts
    TRANSPORT = "TRANSPORT"              # no HTTP-level answer, counts


_CODE_CLASSES: dict[int, ErrorClass] = {
    1: ErrorClass.SYSTEM,
    10: ErrorClass.SYSTEM,
    6: ErrorClass.RATE_GLOBAL,
    29: ErrorClass.RATE_GLOBAL,
    9: ErrorClass.FLOOD_PLAYER,
    984: ErrorClass.SPAM_RESTRICTED,
    900: ErrorClass.CONSENT_LOST,
    901: ErrorClass.CONSENT_LOST,
    902: ErrorClass.CONSENT_LOST,
    1021: ErrorClass.CONSENT_LOST,
    5: ErrorClass.AUTH,
    7: ErrorClass.AUTH,
    15: ErrorClass.AUTH,
    27: ErrorClass.AUTH,
    28: ErrorClass.AUTH,
    100: ErrorClass.BAD_REQUEST,
    911: ErrorClass.BAD_REQUEST,
    914: ErrorClass.TOO_LONG,
    0: ErrorClass.TRANSPORT,
}

# Spec 2.7 "учитывается в аварийном выключателе": system-class failures
# plus transport; per-player and auth/consent outcomes stay out.
_COUNTS_FOR_BREAKER: frozenset[ErrorClass] = frozenset(
    {
        ErrorClass.SYSTEM,
        ErrorClass.RATE_GLOBAL,
        ErrorClass.SPAM_RESTRICTED,
        ErrorClass.BAD_REQUEST,
        ErrorClass.UNKNOWN,
        ErrorClass.TRANSPORT,
    }
)


def classify_vk_error(code: int) -> ErrorClass:
    """Map a VK error code (or 0 for transport) to its ErrorClass."""
    return _CODE_CLASSES.get(code, ErrorClass.UNKNOWN)


def counts_for_breaker(error_class: ErrorClass) -> bool:
    """Whether the class feeds the circuit breaker's failure window."""
    return error_class in _COUNTS_FOR_BREAKER
