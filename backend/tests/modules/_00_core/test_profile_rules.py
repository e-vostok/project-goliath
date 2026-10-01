"""
Pure-function tests for nation profile validation rules (Spec Part 3).

No DB: profile_rules only needs the loaded CoreConfig. Text fields are
checked at min/max/one-off boundaries, for Cc/Cf characters, and for
strip-normalization; the history URL is checked against the exact Part 3
contract (https, allowed host, no port/userinfo/query/fragment, /@slug
path).
"""

from __future__ import annotations

import pytest

from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    HistoryUrlInvalidError,
    LeaderNameInvalidError,
    LeaderTitleInvalidError,
)
from modules._00_core.profile_rules import (
    validate_history_url,
    validate_leader_name,
    validate_leader_title,
)
from tests.fixtures.profile import VALID_PROFILE

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())


class TestLeaderName:
    """leader_name text rules — bounds from nation.leader_name_*."""

    def test_min_and_max_accepted(self):
        nation = CORE_CONFIG.nation
        lo = "a" * nation.leader_name_min_length
        hi = "a" * nation.leader_name_max_length

        assert validate_leader_name(lo, CORE_CONFIG) == lo
        assert validate_leader_name(hi, CORE_CONFIG) == hi

    @pytest.mark.parametrize(
        "value",
        [
            "a" * (CORE_CONFIG.nation.leader_name_min_length - 1),
            "a" * (CORE_CONFIG.nation.leader_name_max_length + 1),
            "",  # empty
            "   ",  # whitespace-only strips to empty
        ],
    )
    def test_out_of_bounds_rejected(self, value):
        with pytest.raises(LeaderNameInvalidError):
            validate_leader_name(value, CORE_CONFIG)

    @pytest.mark.parametrize(
        "value",
        [
            "Ivan\nGrozny",  # inner newline (Cc)
            "Ivan\tGrozny",  # inner tab (Cc)
            "Ivan​Grozny",  # zero-width space (Cf)
        ],
    )
    def test_forbidden_characters_rejected(self, value):
        with pytest.raises(LeaderNameInvalidError):
            validate_leader_name(value, CORE_CONFIG)

    def test_strip_stored(self):
        assert validate_leader_name("  Ivan Grozny  ", CORE_CONFIG) == (
            "Ivan Grozny"
        )


class TestLeaderTitle:
    """leader_title text rules — bounds from nation.leader_title_*."""

    def test_min_and_max_accepted(self):
        nation = CORE_CONFIG.nation
        lo = "a" * nation.leader_title_min_length
        hi = "a" * nation.leader_title_max_length

        assert validate_leader_title(lo, CORE_CONFIG) == lo
        assert validate_leader_title(hi, CORE_CONFIG) == hi

    @pytest.mark.parametrize(
        "value",
        [
            "a" * (CORE_CONFIG.nation.leader_title_min_length - 1),
            "a" * (CORE_CONFIG.nation.leader_title_max_length + 1),
            "",
            "   ",
            "Tsar\nof All",
            "Tsar\tof All",
            "Tsar​of All",
        ],
    )
    def test_invalid_rejected(self, value):
        with pytest.raises(LeaderTitleInvalidError):
            validate_leader_title(value, CORE_CONFIG)

    def test_strip_stored(self):
        assert validate_leader_title("\tSupreme Ruler\n", CORE_CONFIG) == (
            "Supreme Ruler"
        )


class TestHistoryUrl:
    """history_url rules — bounds and host list from the config."""

    @pytest.mark.parametrize(
        "value,stored",
        [
            ("https://vk.com/@club1-abc", "https://vk.com/@club1-abc"),
            ("https://vk.ru/@x", "https://vk.ru/@x"),
            ("https://VK.COM/@x", "https://VK.COM/@x"),
            (
                "  https://vk.com/@club1-abc  ",
                "https://vk.com/@club1-abc",
            ),
        ],
    )
    def test_valid_urls(self, value, stored):
        """Accepted URLs are stored stripped but otherwise untouched."""
        assert validate_history_url(value, CORE_CONFIG) == stored

    @pytest.mark.parametrize(
        "value",
        [
            "http://vk.com/@x",  # non-https scheme
            "https://example.com/@x",  # host not in allow list
            "https://vk.com.evil.com/@x",  # lookalike subdomain trick
            "https://vk.com@evil.com/@x",  # userinfo trick
            "https://vk.com:443/@x",  # explicit port
            "https://vk.com/@x?utm=1",  # query
            "https://vk.com/@x?",  # bare query marker
            "https://vk.com/@x#a",  # fragment
            "https://vk.com/@x/",  # trailing slash in path
            "https://vk.com/wall-1_2",  # not an /@slug path
            "https://vk.com/@",  # empty slug
            "https://vk.com/@x y",  # inner space
            "https://vk.com/\\@x",  # backslash
            "https://[::1/@x",  # unparseable (ValueError -> invalid)
            "",  # empty
            "   ",  # whitespace-only
            "https://vk.com/@" + "x" * CORE_CONFIG.nation.history_url_max_length,  # over limit
        ],
    )
    def test_invalid_urls_rejected(self, value):
        with pytest.raises(HistoryUrlInvalidError):
            validate_history_url(value, CORE_CONFIG)
