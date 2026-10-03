"""
Unit and lifespan tests for core.security.startup_guard (DEP-4).

Unit cases feed validate_production_environment explicit env dicts — the
guard is a pure function of its argument, so os.environ is never touched.
The lifespan case boots the real app through LifespanManager and proves
a strict-mode misconfiguration aborts startup before the engine init.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from dotenv import dotenv_values

from core.security.startup_guard import (
    ProductionConfigError,
    validate_production_environment,
)
from main import app

REPO_ROOT = Path(__file__).resolve().parents[3]

# A 64-char hex key: long, varied, and free of any known placeholder
# substring — the realistic production shape.
_GOOD_JWT = "9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e"


def _valid_env(app_env: str = "production") -> dict[str, str]:
    """An env that passes every strict check; callers break one key."""
    return {
        "APP_ENV": app_env,
        "JWT_SECRET_KEY": _GOOD_JWT,
        "DATABASE_URL": "postgresql+asyncpg://goliath:pw@db:5432/goliath",
        "VK_APP_SECRET": "vk-mini-app-secret-8f6e5d4c",
    }


# ── non-strict APP_ENV ────────────────────────────────────────────────


@pytest.mark.parametrize("app_env", [None, "", "   "])
def test_unset_or_blank_app_env_skips_all_checks(app_env):
    """Local dev and CI keep working: no APP_ENV means no checks."""
    env = {} if app_env is None else {"APP_ENV": app_env}
    validate_production_environment(env)  # must not raise


def test_unrecognised_app_env_warns_but_passes(caplog):
    """A typo like 'prodction' must not silently pass — it warns."""
    with caplog.at_level(logging.WARNING):
        validate_production_environment({"APP_ENV": "prodction"})

    assert any(
        "APP_ENV" in record.getMessage() for record in caplog.records
    )


@pytest.mark.parametrize("app_env", ["production", "prod", "staging"])
def test_strict_envs_accept_valid_configuration(app_env):
    validate_production_environment(_valid_env(app_env))


@pytest.mark.parametrize("app_env", [" production ", "PRODUCTION", "Staging"])
def test_app_env_matching_is_normalised(app_env):
    """Whitespace and case are stripped before the strict-mode check."""
    env = _valid_env(app_env)
    del env["JWT_SECRET_KEY"]
    with pytest.raises(ProductionConfigError):
        validate_production_environment(env)


# ── JWT_SECRET_KEY ────────────────────────────────────────────────────


def test_missing_jwt_rejected():
    env = _valid_env()
    del env["JWT_SECRET_KEY"]
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


def test_short_jwt_rejected():
    env = _valid_env()
    env["JWT_SECRET_KEY"] = "x" * 31
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


def test_single_character_jwt_rejected():
    """A 64-char string of one repeated character is still weak."""
    env = _valid_env()
    env["JWT_SECRET_KEY"] = "a" * 64
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


@pytest.mark.parametrize(
    "placeholder",
    [
        "change_me",
        "changeme",
        "secret",
        "dev",
        "test",
        "your-secret",
        "password",
        "example",
    ],
)
def test_placeholder_jwt_rejected(placeholder):
    """Each known dev placeholder is caught even inside a long key."""
    env = _valid_env()
    env["JWT_SECRET_KEY"] = (
        "prefix-" + placeholder + "-suffix-padding-0123456789"
    )
    assert len(env["JWT_SECRET_KEY"]) >= 32
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


def test_placeholder_jwt_match_is_case_insensitive():
    env = _valid_env()
    env["JWT_SECRET_KEY"] = "My-SECRET-Production-Key-0123456789ab"
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "JWT_SECRET_KEY" in str(exc_info.value)


# ── DATABASE_URL ──────────────────────────────────────────────────────


def test_missing_database_url_rejected():
    env = _valid_env()
    del env["DATABASE_URL"]
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "DATABASE_URL" in str(exc_info.value)


def test_sqlite_database_url_rejected():
    env = _valid_env()
    env["DATABASE_URL"] = "sqlite+aiosqlite:///./dev.db"
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "DATABASE_URL" in str(exc_info.value)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://u:pw@localhost:5432/goliath",
        "postgresql+asyncpg://u:pw@127.0.0.1:5432/goliath",
        "postgresql+asyncpg://u:pw@[::1]:5432/goliath",
        "postgresql+asyncpg://u:pw@/goliath",
    ],
)
def test_loopback_database_url_rejected(database_url):
    env = _valid_env()
    env["DATABASE_URL"] = database_url
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "DATABASE_URL" in str(exc_info.value)


def test_unparseable_database_url_rejected():
    env = _valid_env()
    env["DATABASE_URL"] = "not-a-url"
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "DATABASE_URL" in str(exc_info.value)


# ── VK_APP_SECRET ─────────────────────────────────────────────────────


def test_missing_vk_app_secret_rejected():
    env = _valid_env()
    del env["VK_APP_SECRET"]
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "VK_APP_SECRET" in str(exc_info.value)


def test_change_me_vk_app_secret_rejected():
    env = _valid_env()
    env["VK_APP_SECRET"] = "CHANGE_ME"
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)
    assert "VK_APP_SECRET" in str(exc_info.value)


# ── message contract ──────────────────────────────────────────────────


def test_all_problems_listed_at_once():
    """A fully broken env yields ONE error naming ALL bad variables."""
    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment({"APP_ENV": "production"})

    message = str(exc_info.value)
    assert "JWT_SECRET_KEY" in message
    assert "DATABASE_URL" in message
    assert "VK_APP_SECRET" in message


def test_secret_values_never_appear_in_message():
    """The message names variables only — values are never leaked."""
    jwt_value = "weak-jwt-0123456789abcdef"  # 24 chars -> too short
    db_value = "postgresql+asyncpg://user:Sup3rSecretPW@localhost:5432/db"
    vk_value = "prefix-CHANGE_ME-7f8a9b"
    env = {
        "APP_ENV": "production",
        "JWT_SECRET_KEY": jwt_value,
        "DATABASE_URL": db_value,
        "VK_APP_SECRET": vk_value,
    }

    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)

    message = str(exc_info.value)
    for name in ("JWT_SECRET_KEY", "DATABASE_URL", "VK_APP_SECRET"):
        assert name in message
    for value in (jwt_value, "Sup3rSecretPW", vk_value, "7f8a9b"):
        assert value not in message


def test_prod_example_template_values_rejected():
    """.env.prod.example as shipped (CHANGE_ME placeholders) must fail."""
    env = {
        key: value
        for key, value in dotenv_values(
            REPO_ROOT / ".env.prod.example"
        ).items()
        if value is not None
    }
    assert env["APP_ENV"] == "production"

    with pytest.raises(ProductionConfigError) as exc_info:
        validate_production_environment(env)

    message = str(exc_info.value)
    assert "JWT_SECRET_KEY" in message
    assert "VK_APP_SECRET" in message


def test_realistic_production_env_passes():
    """A 64-hex JWT and a compose-network DATABASE_URL host are valid."""
    validate_production_environment(_valid_env())


# ── lifespan integration ─────────────────────────────────────────────


async def test_lifespan_refuses_weak_production_jwt(monkeypatch):
    """APP_ENV=production + a weak JWT aborts startup before DB init."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "tiny-key")
    # The remaining strict inputs are valid so the error names ONLY the
    # JWT — and init_engine is never reached, so the host need not exist.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://u:pw@db:5432/goliath"
    )
    monkeypatch.setenv("VK_APP_SECRET", "vk-mini-app-secret-8f6e5d4c")

    with pytest.raises(ProductionConfigError) as exc_info:
        async with LifespanManager(app):
            pass

    assert "JWT_SECRET_KEY" in str(exc_info.value)
    assert "tiny-key" not in str(exc_info.value)
