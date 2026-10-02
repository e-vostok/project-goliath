"""
Fixtures for the PostgreSQL verification suite (Issue 9).

These tests are DESTRUCTIVE by design: they wipe the target database's
public schema and rebuild it from Alembic migrations. Two hard guards
stand between a typo and a wiped dev database:

- ``assert_safe_test_db`` — a pure function, checked BEFORE any
  connection is opened: the ``DATABASE_URL_TEST`` database name must end
  with ``_test`` and must differ from the ``DATABASE_URL`` database name.
- ``DATABASE_URL_TEST`` empty/unset -> every PG test SKIPs (or FAILs
  under ``REQUIRE_POSTGRES_TESTS=1``, so CI cannot silently green).

``pg_schema`` upgrades to ``head`` by default; ``PG_TEST_REVISION``
overrides the target so the drift guard can be red-checked against a
deliberately stale schema (e.g. revision 0004).

Anti-Mock Guard: the app is served through its real ASGI lifespan on the
production engine path (``init_engine``) — no ``get_session`` override,
no mocked DB/HTTP/orchestrator anywhere in this suite.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.admin.registry import AdminRegistry
from core.tick.orchestrator import TickOrchestrator
from main import app  # noqa: F401 — importing main loads the root .env
from tests.modules._00_core.test_router import TEST_JWT_SECRET, TEST_VK_SECRET

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
ENV_PATH = REPO_ROOT / ".env"

ADMIN_VK_ID = 424242

_SKIP_REASON = (
    "DATABASE_URL_TEST is not set — skipping PostgreSQL tests "
    "(set it in .env or the environment; the database name must end "
    "with '_test')"
)


def _load_env() -> None:
    """Load the repo-root .env the same way src/main.py does."""
    load_dotenv(dotenv_path=ENV_PATH)


def _database_name(url: str | None) -> str | None:
    """Database name component of a SQLAlchemy URL, or None."""
    if not url:
        return None
    try:
        return make_url(url).database or None
    except Exception:
        return None


def _sync_url(async_url: str) -> str:
    """postgresql+asyncpg URL -> psycopg2 (sync) equivalent."""
    return make_url(async_url).set(
        drivername="postgresql+psycopg2"
    ).render_as_string(hide_password=False)


def assert_safe_test_db(test_url: str, dev_url: str | None) -> None:
    """
    Fail (pytest.fail) unless test_url names a dedicated *_test database.

    Pure function — no connection is opened. Refuses when the URL is not
    PostgreSQL, carries no database name, the name lacks the ``_test``
    suffix, or it equals the DATABASE_URL (development) database name.
    """
    try:
        parsed = make_url(test_url)
    except Exception as exc:
        pytest.fail(
            f"DATABASE_URL_TEST is not a parseable SQLAlchemy URL: {exc}"
        )

    driver = parsed.drivername
    if not (driver == "postgres" or driver.startswith("postgresql")):
        pytest.fail(
            f"DATABASE_URL_TEST driver '{driver}' is not PostgreSQL — "
            "these tests wipe the target database, refusing to run "
            "against a non-PostgreSQL URL"
        )

    test_db = parsed.database
    if not test_db:
        pytest.fail(
            "DATABASE_URL_TEST carries no database name — refusing to "
            "wipe an unnamed/default database"
        )
    if not test_db.endswith("_test"):
        pytest.fail(
            f"Refusing to run destructive tests against database "
            f"'{test_db}': the DATABASE_URL_TEST database name must end "
            "with '_test'"
        )

    dev_db = _database_name(dev_url)
    if dev_db is not None and dev_db == test_db:
        pytest.fail(
            f"DATABASE_URL_TEST points at database '{test_db}', the same "
            "name as DATABASE_URL — refusing to wipe the development "
            "database"
        )


@pytest.fixture(scope="session")
def pg_url() -> str:
    """
    Validated asyncpg URL for the throwaway test database.

    Unset/empty DATABASE_URL_TEST skips the suite; REQUIRE_POSTGRES_TESTS=1
    turns the skip into a failure. The guard runs before any connection.
    """
    _load_env()
    raw = (os.environ.get("DATABASE_URL_TEST") or "").strip()
    if not raw:
        if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail(
                "REQUIRE_POSTGRES_TESTS=1 but DATABASE_URL_TEST is "
                f"empty or unset (checked environment and {ENV_PATH})"
            )
        pytest.skip(_SKIP_REASON)
    assert_safe_test_db(raw, os.environ.get("DATABASE_URL"))
    return make_url(raw).set(
        drivername="postgresql+asyncpg"
    ).render_as_string(hide_password=False)


def _reset_public_schema(sync_url: str) -> str:
    """
    Empty the public schema. Returns 'schema' when DROP SCHEMA CASCADE
    succeeded, 'tables' when privileges forced the per-table fallback.
    """
    engine = sa.create_engine(sync_url)
    try:
        try:
            with engine.begin() as conn:
                conn.execute(sa.text("DROP SCHEMA public CASCADE"))
                conn.execute(sa.text("CREATE SCHEMA public"))
            return "schema"
        except sa.exc.SQLAlchemyError:
            pass
        # Fallback: no privilege to drop the schema itself — drop every
        # table (alembic_version included) instead.
        with engine.begin() as conn:
            tables = (
                conn.execute(
                    sa.text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public'"
                    )
                )
                .scalars()
                .all()
            )
            for table in tables:
                conn.execute(
                    sa.text(f'DROP TABLE IF EXISTS "{table}" CASCADE')
                )
        return "tables"
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def pg_schema(pg_url: str) -> str:
    """
    Rebuild the test database schema once per session: wipe public, then
    ``alembic upgrade`` to head (or PG_TEST_REVISION for drift red-checks).
    Yields the asyncpg URL.
    """
    sync_url = _sync_url(pg_url)
    mode = _reset_public_schema(sync_url)
    target = os.environ.get("PG_TEST_REVISION", "head")
    print(f"[pg_schema] reset mode: {mode}; alembic target: {target}")
    # Alembic's env.py reads DATABASE_URL; a bare "postgresql://" would
    # resolve to psycopg3 (not installed), so hand it the psycopg2 URL.
    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("DATABASE_URL", sync_url)
        alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        command.upgrade(alembic_cfg, target)
    return pg_url


@pytest.fixture(autouse=True)
def pg_clean(pg_schema: str) -> None:
    """
    Per-test data reset (autouse in the PG test modules).

    Plain SQL in a fixed order; NEVER TRUNCATE … CASCADE — provinces are
    wiped too: migration 0006 removed the placeholder seed, so tests
    seed exactly the province rows they use. next_tick_at is pushed a
    day out so the app's background scheduler never fires mid-test.
    """
    engine = sa.create_engine(_sync_url(pg_schema))
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM map_ownership_log"))
            conn.execute(sa.text("DELETE FROM provinces"))
            conn.execute(sa.text("DELETE FROM scheduled_actions"))
            conn.execute(sa.text("DELETE FROM nations"))
            conn.execute(sa.text("DELETE FROM players"))
            conn.execute(sa.text("DELETE FROM tick_log"))
            conn.execute(
                sa.text(
                    "UPDATE game_clock SET current_turn = 0, "
                    "last_tick_at = NULL, "
                    "next_tick_at = now() + interval '1 day'"
                )
            )
    finally:
        engine.dispose()


@pytest_asyncio.fixture
async def pg_live_client(
    pg_url: str, pg_clean: None, monkeypatch
) -> AsyncGenerator[AsyncClient, None]:
    """
    The real app over its real ASGI lifespan on the migrated PostgreSQL
    test DB (the test_app_startup.py / test_tick_file_sqlite.py pattern).
    No get_session override — requests hit the production engine that
    lifespan's init_engine() builds. Class-level AdminRegistry and
    TickOrchestrator registries are snapshotted and restored so lifespan
    wiring cannot leak into the rest of the suite.
    """
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("ADMIN_VK_USER_IDS", str(ADMIN_VK_ID))

    saved_views = AdminRegistry.get_state_view_hooks()
    saved_resets = AdminRegistry.get_reset_hooks()
    saved_handlers = {
        phase: list(handlers)
        for phase, handlers in TickOrchestrator._handlers.items()
    }
    saved_finalize = TickOrchestrator._finalize_callback

    async with LifespanManager(app) as manager:
        transport = ASGITransport(app=manager.app)
        async with AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client

    AdminRegistry._state_view_hooks.clear()
    AdminRegistry._state_view_hooks.update(saved_views)
    AdminRegistry._reset_hooks.clear()
    AdminRegistry._reset_hooks.update(saved_resets)
    TickOrchestrator._handlers.clear()
    TickOrchestrator._handlers.update(saved_handlers)
    TickOrchestrator._finalize_callback = saved_finalize


@pytest_asyncio.fixture
async def pg_db(
    pg_url: str, pg_clean: None
) -> AsyncGenerator[async_sessionmaker, None]:
    """
    A second, app-independent asyncpg engine/session maker for DB-direct
    assertions — a different connection from the app's, so it only ever
    sees truly committed state. Disposed after the test.
    """
    engine = create_async_engine(pg_url)
    maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    yield maker
    await engine.dispose()
