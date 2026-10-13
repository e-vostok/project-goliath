"""
Tests for VK error classification (Spec 2.7, Appendix T: T10, T23).

Every code maps to its ErrorClass, and each class carries the correct
"counts toward the circuit breaker" flag.
"""

from __future__ import annotations

import pytest

from modules._02_bot.errors import (
    ErrorClass,
    classify_vk_error,
    counts_for_breaker,
)


@pytest.mark.parametrize(
    "code,expected",
    [
        (0, ErrorClass.TRANSPORT),
        (1, ErrorClass.SYSTEM),
        (10, ErrorClass.SYSTEM),
        (6, ErrorClass.RATE_GLOBAL),
        (29, ErrorClass.RATE_GLOBAL),
        (9, ErrorClass.FLOOD_PLAYER),
        (984, ErrorClass.SPAM_RESTRICTED),
        (900, ErrorClass.CONSENT_LOST),
        (901, ErrorClass.CONSENT_LOST),
        (902, ErrorClass.CONSENT_LOST),
        (1021, ErrorClass.CONSENT_LOST),
        (5, ErrorClass.AUTH),
        (7, ErrorClass.AUTH),
        (15, ErrorClass.AUTH),
        (27, ErrorClass.AUTH),
        (28, ErrorClass.AUTH),
        (100, ErrorClass.BAD_REQUEST),
        (911, ErrorClass.BAD_REQUEST),
        (914, ErrorClass.TOO_LONG),
        (777, ErrorClass.UNKNOWN),
        (-3, ErrorClass.UNKNOWN),
    ],
)
def test_classify_vk_error(code, expected):
    assert classify_vk_error(code) == expected


@pytest.mark.parametrize(
    "error_class,counts",
    [
        (ErrorClass.SYSTEM, True),
        (ErrorClass.RATE_GLOBAL, True),
        (ErrorClass.SPAM_RESTRICTED, True),
        (ErrorClass.BAD_REQUEST, True),
        (ErrorClass.UNKNOWN, True),
        (ErrorClass.TRANSPORT, True),
        (ErrorClass.FLOOD_PLAYER, False),
        (ErrorClass.CONSENT_LOST, False),
        (ErrorClass.AUTH, False),
        (ErrorClass.TOO_LONG, False),
    ],
)
def test_counts_for_breaker(error_class, counts):
    assert counts_for_breaker(error_class) is counts
