"""
Pure unit tests for assert_safe_test_db (tests/fixtures/postgres.py).

The guard is the last line of defence between a misconfigured
DATABASE_URL_TEST and a wiped development database. These tests exercise
it as a pure function — no connection is ever opened, so they run in
every suite, with or without a reachable PostgreSQL.
"""

from __future__ import annotations

import pytest
from _pytest.outcomes import Failed

from tests.fixtures.postgres import assert_safe_test_db

pytestmark = pytest.mark.postgres

DEV_PG = "postgresql://dev:devpass@127.0.0.1:5432/goliath"
DEV_PG_TEST = "postgresql://dev:devpass@127.0.0.1:5432/goliath_test"
DEV_SQLITE = "sqlite+aiosqlite:///./dev.db"


class TestSafeUrls:
    """URLs the guard must accept: *_test name, different from dev."""

    @pytest.mark.parametrize(
        "test_url",
        [
            "postgresql+asyncpg://t:t@127.0.0.1:5432/goliath_test",
            "postgresql://t:t@db.internal:5432/goliath_test",
            "postgres://t:t@127.0.0.1/goliath_test",
            "postgresql+psycopg2://t:t@127.0.0.1/goliath_test",
        ],
    )
    def test_accepted_urls(self, test_url):
        assert assert_safe_test_db(test_url, DEV_PG) is None

    def test_sqlite_dev_url_still_safe(self):
        assert (
            assert_safe_test_db(
                "postgresql+asyncpg://t:t@127.0.0.1/goliath_test",
                DEV_SQLITE,
            )
            is None
        )

    def test_unset_dev_url_still_safe(self):
        assert (
            assert_safe_test_db(
                "postgresql+asyncpg://t:t@127.0.0.1/goliath_test", None
            )
            is None
        )
        assert (
            assert_safe_test_db(
                "postgresql+asyncpg://t:t@127.0.0.1/goliath_test", ""
            )
            is None
        )


class TestRejectedUrls:
    """Every unsafe shape must fail BEFORE any connection is opened."""

    def test_name_without_test_suffix(self):
        with pytest.raises(Failed, match="_test"):
            assert_safe_test_db(
                "postgresql+asyncpg://t:t@127.0.0.1/goliath", DEV_PG
            )

    def test_dev_database_name_is_rejected_even_with_suffix_prefix(self):
        """goliath_dev does not end with _test — the classic foot-gun."""
        with pytest.raises(Failed, match="_test"):
            assert_safe_test_db(
                "postgresql://t:t@127.0.0.1/goliath_dev", DEV_SQLITE
            )

    def test_same_database_name_as_dev(self):
        """Same name on any host is refused — name comparison is global."""
        with pytest.raises(Failed, match="same"):
            assert_safe_test_db(
                "postgresql+asyncpg://t:t@10.0.0.9/goliath_test",
                DEV_PG_TEST,
            )

    @pytest.mark.parametrize(
        "test_url",
        [
            "postgresql+asyncpg://t:t@127.0.0.1/",
            "postgresql://t:t@127.0.0.1",
        ],
    )
    def test_missing_database_name(self, test_url):
        with pytest.raises(Failed, match="no database name"):
            assert_safe_test_db(test_url, DEV_PG)

    @pytest.mark.parametrize(
        "test_url",
        [
            "sqlite+aiosqlite:///./goliath_test.db",
            "sqlite:///goliath_test",
            "mysql+pymysql://t:t@127.0.0.1/goliath_test",
        ],
    )
    def test_non_postgres_url(self, test_url):
        """Even a *_test-looking name is refused on a non-PG driver."""
        with pytest.raises(Failed, match="not PostgreSQL"):
            assert_safe_test_db(test_url, DEV_SQLITE)
