"""
Shared database-URL resolution.

One rule for every entry point (the application in src/main.py, the
Alembic environment in alembic/env.py): ``DATABASE_URL`` comes from the
process environment first, otherwise from the repository-root ``.env``
file — bound to the repository root, never to the current working
directory, so it resolves identically from ``backend/``,
``backend/src``, or anywhere else.

There is no default and no silent fallback: an unresolvable URL raises
RuntimeError naming the variable and the .env file that was checked.
Previously ``alembic/env.py`` defaulted to ``sqlite:///:memory:``, which
made ``alembic upgrade head`` run all migrations against a throwaway
in-memory database while printing ``Context impl SQLiteImpl``.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine.url import make_url

# This file lives at backend/src/core/settings.py, so parents[3] is the
# repository root — same binding main.py uses for load_dotenv.
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"


def resolve_database_url(env_path: Path | None = None) -> str:
    """
    Resolve the application's database URL.

    The process environment wins; otherwise the .env file at ``env_path``
    (default: the repository-root .env) is consulted. The .env file is
    only read — it is not merged into os.environ, so a resolved value
    never leaks into the environment of other consumers.

    Raises:
        RuntimeError: when no URL can be resolved; the message names the
            variable and the .env file that was checked.
    """
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url

    path = Path(env_path) if env_path is not None else ENV_PATH
    file_values = dotenv_values(path)
    url = (file_values.get("DATABASE_URL") or "").strip()
    if url:
        return url

    raise RuntimeError(
        "DATABASE_URL is not set: it was found neither in the process "
        f"environment nor in {path}. Set DATABASE_URL in the environment "
        "or in the repository-root .env file."
    )


def to_sync_database_url(url: str) -> str:
    """
    Convert an async SQLAlchemy URL into its synchronous counterpart.

    Alembic's env.py runs synchronous ``create_engine``; the
    application's ``postgresql+asyncpg://`` and ``sqlite+aiosqlite://``
    forms must not reach it raw. Textual suffix-stripping (the old env.py
    approach) produced a bare ``postgresql://`` whose resolved driver is
    whatever the environment happens to install — the production URL
    must land on the driver that is actually declared: psycopg2.

    Rules:
    - any ``postgresql`` backend (+asyncpg, +psycopg, +psycopg2, bare,
      pg8000, aiopg, …) normalises to ``postgresql+psycopg2``;
    - ``sqlite+aiosqlite`` → ``sqlite``;
    - legacy async suffixes on other backends (+asyncmy, +aiomysql,
      +aiopg) strip to the bare backend, as the old env.py did;
    - anything else is returned unchanged.

    Components are preserved verbatim — username, percent-encoded
    password, host, port, database, query — via make_url().set().
    SQLite URLs swap the driver textually so ``:memory:`` and ``./``
    paths can never come out percent-encoded.
    """
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "postgresql":
        if parsed.drivername == "postgresql+psycopg2":
            return url
        return parsed.set(
            drivername="postgresql+psycopg2"
        ).render_as_string(hide_password=False)
    if parsed.drivername == "sqlite+aiosqlite":
        return url.replace("+aiosqlite", "", 1)
    for suffix in ("+asyncmy", "+aiomysql", "+aiopg"):
        if parsed.drivername.endswith(suffix):
            return parsed.set(
                drivername=backend
            ).render_as_string(hide_password=False)
    return url


def format_database_target(url: str) -> str:
    """
    Render a database URL for logs with the password masked.

    SQLite URLs carry no password, so they are shown as given —
    render_as_string() on some SQLAlchemy versions percent-encodes the
    ':' in sqlite:///:memory: paths, which would print a misleading
    "sqlite:///%3Amemory%3A" target.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return url
    return parsed.render_as_string(hide_password=True)
