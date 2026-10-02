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
