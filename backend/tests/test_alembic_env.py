"""
Tests for Alembic's database-URL resolution (alembic/env.py →
core.settings.resolve_database_url).

Regression for the bug where `alembic upgrade head` silently fell back
to an in-memory SQLite database because env.py never loaded the
repo-root `.env`: migrations printed "Context impl SQLiteImpl" and the
application's PostgreSQL was never touched.

Rule (same as the application's): the process environment wins;
otherwise the root `.env` is read — bound to the repository root, not
to the current working directory. No silent fallback: an unresolvable
URL is a hard error that names the variable and the .env file.

No mocks of alembic/SQLAlchemy — real temp directories, real engines,
real `command.upgrade` runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from core.settings import (
    format_database_target,
    resolve_database_url,
)
import core.settings as core_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic_cfg() -> Config:
    return Config(str(BACKEND_DIR / "alembic.ini"))


class TestResolveDatabaseUrl:
    def test_environment_variable_wins(self, monkeypatch, tmp_path):
        url = f"sqlite:///{(tmp_path / 'env.db').as_posix()}"
        monkeypatch.setenv("DATABASE_URL", url)

        assert resolve_database_url() == url

    def test_environment_wins_over_env_file(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DATABASE_URL=sqlite:///from_file.db\n", encoding="utf-8"
        )
        url = "sqlite:///from_env.db"
        monkeypatch.setenv("DATABASE_URL", url)

        assert resolve_database_url(env_path=env_file) == url

    def test_root_env_file_fallback_is_cwd_independent(
        self, monkeypatch, tmp_path
    ):
        """A root-style .env supplies the URL when the environment is
        empty — the file is found by absolute path, not by cwd."""
        fake_root = tmp_path / "repo"
        fake_root.mkdir()
        env_file = fake_root / ".env"
        db_file = fake_root / "file.db"
        url = f"sqlite:///{db_file.as_posix()}"
        env_file.write_text(f"DATABASE_URL={url}\n", encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # An unrelated working directory must not matter.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        assert resolve_database_url(env_path=env_file) == url

    def test_env_file_quotes_are_parsed(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        url = "postgresql+asyncpg://u:s@h:5432/db"
        env_file.write_text(f'DATABASE_URL="{url}"\n', encoding="utf-8")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        assert resolve_database_url(env_path=env_file) == url

    def test_missing_url_fails_loudly(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        missing_env = tmp_path / "no_such.env"

        with pytest.raises(RuntimeError) as exc_info:
            resolve_database_url(env_path=missing_env)

        message = str(exc_info.value)
        assert "DATABASE_URL" in message
        assert str(missing_env) in message


class TestAlembicEndToEnd:
    def test_upgrade_uses_environment_url(self, tmp_path, monkeypatch, capsys):
        db_file = tmp_path / "target.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )

        command.upgrade(_alembic_cfg(), "head")

        assert db_file.exists()
        engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
        try:
            with engine.connect() as conn:
                version = conn.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                ).scalar_one()
        finally:
            engine.dispose()
        assert version == "0006"

        # One masked target line was printed, with no password and no
        # silent SQLite fallback.
        err = capsys.readouterr().err
        target_lines = [
            line for line in err.splitlines() if "Alembic target:" in line
        ]
        assert len(target_lines) == 1
        assert target_lines[0].startswith("Alembic target: sqlite:///")
        assert "target.db" in target_lines[0]

    def test_upgrade_uses_env_file_fallback(self, tmp_path, monkeypatch):
        """With an empty environment, alembic reads the repo-root .env —
        here redirected to a temp file via the ENV_PATH seam."""
        db_file = tmp_path / "from_env_file.db"
        env_file = tmp_path / ".env"
        env_file.write_text(
            f"DATABASE_URL=sqlite:///{db_file.as_posix()}\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(core_settings, "ENV_PATH", env_file)

        command.upgrade(_alembic_cfg(), "head")

        assert db_file.exists()

    def test_missing_url_aborts_before_any_migration(
        self, tmp_path, monkeypatch
    ):
        """No URL anywhere → RuntimeError naming the variable and the
        .env path, and not a single database file is created."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr(
            core_settings, "ENV_PATH", tmp_path / ".env"  # absent
        )

        with pytest.raises(RuntimeError) as exc_info:
            command.upgrade(_alembic_cfg(), "head")

        assert "DATABASE_URL" in str(exc_info.value)
        assert list(tmp_path.glob("*.db")) == []


class TestToSyncDatabaseUrl:
    """
    to_sync_database_url() (FIX-ENV) converts async driver URLs into
    the synchronous form env.py feeds to create_engine().

    The old env.py stripped "+asyncpg" textually: the resulting bare
    ``postgresql://`` resolves to psycopg3 on SQLAlchemy 2.x — not
    installed — while the production .env ships exactly that asyncpg
    shape. Every postgresql driver form must normalise to psycopg2.
    """

    @pytest.mark.parametrize(
        "url,expected",
        [
            # The production shape: asyncpg -> psycopg2.
            (
                "postgresql+asyncpg://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            # Bare postgresql -> psycopg2 (never psycopg3-by-default).
            (
                "postgresql://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            # Already the sync driver: verbatim.
            (
                "postgresql+psycopg2://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            # Other postgres drivers normalise too.
            (
                "postgresql+psycopg://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            (
                "postgresql+pg8000://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            (
                "postgresql+aiopg://u:p@h:5432/d",
                "postgresql+psycopg2://u:p@h:5432/d",
            ),
            # Percent-encoded password (@ and /) survives byte-for-byte.
            (
                "postgresql+asyncpg://u:p%40ss%2Fw@h:5432/d",
                "postgresql+psycopg2://u:p%40ss%2Fw@h:5432/d",
            ),
            # Query parameters are preserved (render_as_string emits
            # them in canonical key order).
            (
                "postgresql+asyncpg://u:p@h:5432/d"
                "?sslmode=require&application_name=goliath",
                "postgresql+psycopg2://u:p@h:5432/d"
                "?application_name=goliath&sslmode=require",
            ),
            # SQLite: aiosqlite strips to the bare sync form; paths and
            # ':memory:' come out unchanged — never percent-encoded.
            ("sqlite+aiosqlite:///./dev.db", "sqlite:///./dev.db"),
            ("sqlite+aiosqlite:///:memory:", "sqlite:///:memory:"),
            # Already-sync URLs are returned unchanged.
            ("sqlite:///:memory:", "sqlite:///:memory:"),
            ("sqlite:///C:/data/dev.db", "sqlite:///C:/data/dev.db"),
            # Legacy async suffixes on non-postgres backends strip to
            # bare, as the old env.py did.
            ("mysql+asyncmy://u:p@h/d", "mysql://u:p@h/d"),
            ("mysql+aiomysql://u:p@h/d", "mysql://u:p@h/d"),
        ],
    )
    def test_conversion(self, url, expected):
        from core.settings import to_sync_database_url

        assert to_sync_database_url(url) == expected


class TestLoggingPreservation:
    def test_upgrade_does_not_disable_existing_loggers(
        self, tmp_path, monkeypatch
    ):
        """fileConfig() in env.py must not disable loggers created
        before the upgrade: in-process alembic runs (tests, tooling)
        share the interpreter with the application (FIX-ENV)."""
        import logging

        db_file = tmp_path / "loggers.db"
        monkeypatch.setenv(
            "DATABASE_URL", f"sqlite:///{db_file.as_posix()}"
        )
        sentinel = logging.getLogger("tests.sentinel")
        sentinel.disabled = False

        command.upgrade(_alembic_cfg(), "head")

        assert db_file.exists()
        assert logging.getLogger("tests.sentinel").disabled is False


class TestTargetMasking:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "postgresql+asyncpg://goliath_user:Secret123@localhost:5432/goliath_dev",
                "postgresql+asyncpg://goliath_user:***@localhost:5432/goliath_dev",
            ),
            (
                "postgresql://u:p%40ss%3Aw0rd@h:5432/db",  # 'p@ss:w0rd'
                "postgresql://u:***@h:5432/db",
            ),
            (
                "sqlite:///:memory:",
                "sqlite:///:memory:",
            ),
            (
                "sqlite:///C:/data/dev.db",
                "sqlite:///C:/data/dev.db",
            ),
        ],
    )
    def test_masking(self, url, expected):
        rendered = format_database_target(url)
        assert rendered == expected

    def test_password_never_leaks(self):
        """Secrets with URL-significant characters are embedded via
        make_url().set() so the URL itself is always valid — the rendered
        target must still show only '***'."""
        for secret in ["S3cret!", "p@ss:w0rd", "a/b?c#d", "%%%"]:
            url = (
                sa.engine.make_url("postgresql://h:5432/db")
                .set(username="user", password=secret)
                .render_as_string(hide_password=False)
            )
            rendered = format_database_target(url)
            assert secret not in rendered
            assert "***" in rendered
