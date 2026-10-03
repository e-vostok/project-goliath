"""
Production startup guard (DEP-4, Spec deploy.md §8).

Fails fast at boot when APP_ENV marks the deployment as real and the
environment still carries development-grade secrets or a local database.
The guard runs as the very first statement of the FastAPI lifespan —
before config validation and engine init — so a misconfigured production
process dies immediately with a clear message instead of serving
requests on a weak JWT key or a throwaway SQLite file.

The error message names only the offending VARIABLES, never their
values: .env contents are secrets and must not reach logs or CI output.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

_STRICT_APP_ENVS = {"production", "prod", "staging"}

_JWT_MIN_LENGTH = 32

# Case-insensitive substrings that mark a placeholder, not a real secret.
_JWT_PLACEHOLDERS = (
    "change_me",
    "changeme",
    "secret",
    "dev",
    "test",
    "your-secret",
    "password",
    "example",
)

_LOCAL_DB_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


class ProductionConfigError(RuntimeError):
    """Raised when a strict-mode environment fails validation at boot."""


def _jwt_problems(jwt_key: str) -> str | None:
    """The single most relevant JWT problem, or None when acceptable."""
    if not jwt_key:
        return "JWT_SECRET_KEY is not set"
    if len(jwt_key) < _JWT_MIN_LENGTH:
        return (
            f"JWT_SECRET_KEY is shorter than {_JWT_MIN_LENGTH} characters"
        )
    if len(set(jwt_key)) == 1:
        return "JWT_SECRET_KEY consists of a single repeated character"
    lowered = jwt_key.lower()
    for placeholder in _JWT_PLACEHOLDERS:
        if placeholder in lowered:
            return (
                "JWT_SECRET_KEY matches a known development placeholder "
                f"('{placeholder}')"
            )
    return None


def _database_url_problems(database_url: str) -> str | None:
    """The single most relevant DATABASE_URL problem, or None."""
    if not database_url:
        return "DATABASE_URL is not set"
    try:
        url = make_url(database_url)
    except Exception:
        return "DATABASE_URL is not a parseable SQLAlchemy URL"
    if url.drivername.startswith("sqlite"):
        return "DATABASE_URL points at SQLite — production requires PostgreSQL"
    host = (url.host or "").strip().strip("[]")
    if host in _LOCAL_DB_HOSTS:
        return "DATABASE_URL points at a loopback/local database host"
    return None


def _vk_app_secret_problems(vk_app_secret: str) -> str | None:
    """The VK app secret problem, or None."""
    if not vk_app_secret:
        return "VK_APP_SECRET is not set"
    if "change_me" in vk_app_secret.lower():
        return "VK_APP_SECRET still holds the CHANGE_ME placeholder"
    return None


def validate_production_environment(env: Mapping[str, str]) -> None:
    """
    Refuse to boot a strict-mode deployment on unsafe settings.

    Strict mode applies when APP_ENV (stripped, lowercased) is
    "production", "prod" or "staging". An unset/empty APP_ENV skips every
    check — local development and CI keep working unchanged. Any other
    non-empty value skips the checks too but logs a warning, because a
    typo like "prodction" must not silently disable the guard.

    Raises ProductionConfigError listing EVERY problem at once, naming
    variables only — secret values are never included.

    Checked variables: JWT_SECRET_KEY (set, >= 32 chars, not a single
    repeated character, no known dev placeholder), DATABASE_URL (set,
    parseable, non-SQLite, non-local host), VK_APP_SECRET (set, not the
    CHANGE_ME template value). POSTGRES_PASSWORD is deliberately not
    checked — it is consumed by the db container only.
    """
    app_env = (env.get("APP_ENV") or "").strip().lower()
    if not app_env:
        return
    if app_env not in _STRICT_APP_ENVS:
        logger.warning(
            "Unrecognised APP_ENV value — production startup checks "
            "not enforced (expected one of %s)",
            sorted(_STRICT_APP_ENVS),
        )
        return

    problems = [
        problem
        for problem in (
            _jwt_problems(env.get("JWT_SECRET_KEY") or ""),
            _database_url_problems(env.get("DATABASE_URL") or ""),
            _vk_app_secret_problems(env.get("VK_APP_SECRET") or ""),
        )
        if problem is not None
    ]
    if problems:
        raise ProductionConfigError(
            f"Refusing to start with APP_ENV={app_env}: "
            + "; ".join(problems)
        )
