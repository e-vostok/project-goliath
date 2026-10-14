"""
Startup wiring of module 03_registry (Spec 2.5).

``startup_registry()`` runs from the app lifespan after every other
``startup_*`` — synchronous (no database, no network, no background
tasks; the profile worker lives in ``profile_worker.py`` and starts
separately via ``start_profile_worker_if_ready``) and idempotent:

1. load and validate ``configs/03_registry.yaml`` — always, even with
   ``profiles.enabled = false``: a broken YAML must stop the server;
2. register the built-in sources ``players`` and ``nations``
   (Appendix A);
3. check the config against the source registry (INV-R3): every
   ``tables[].source`` must name a registered source and every
   ``columns[].source`` a key of its ``provides`` — a mismatch raises
   ``RegistryConfigError`` and aborts the boot;
4. register the admin state hook (Spec 5.4) — there is no reset hook
   (D9: profiles describe people, not world state).

The validated config is kept in a module-level holder for
``get_registry_config()`` so the sources and ``build_table`` never
re-read the YAML.
"""

from __future__ import annotations

import logging

from modules._03_registry.admin_hooks import register_registry_admin_hooks
from modules._03_registry.config_schema import RegistryConfig
from modules._03_registry.errors import RegistryConfigError
from modules._03_registry.registry import get_table_source
from modules._03_registry.sources import register_builtin_sources

logger = logging.getLogger(__name__)

_registry_config: RegistryConfig | None = None


def get_registry_config() -> RegistryConfig:
    """The config loaded by :func:`startup_registry`; raises before it ran."""
    if _registry_config is None:
        raise RuntimeError(
            "RegistryConfig is not loaded — startup_registry() has not run"
        )
    return _registry_config


def validate_sources_against_config(config: RegistryConfig) -> None:
    """
    Spec 2.5 step 3 (INV-R3): the config must not reference a source that
    nobody registered, nor a value key outside the source's ``provides``.
    """
    for table in config.tables:
        source = get_table_source(table.source)
        if source is None:
            raise RegistryConfigError(
                f"tables.{table.id}: source '{table.source}' is not "
                "registered by any module"
            )
        for column in table.columns:
            if column.source not in source.provides:
                raise RegistryConfigError(
                    f"tables.{table.id}.columns.{column.id}: source key "
                    f"'{column.source}' is not in provides of source "
                    f"'{table.source}' ({sorted(source.provides)})"
                )


def startup_registry() -> RegistryConfig:
    """Boot the module's static parts; returns the validated config."""
    global _registry_config
    config = RegistryConfig.from_yaml(RegistryConfig.get_default_config_path())
    register_builtin_sources()
    validate_sources_against_config(config)
    register_registry_admin_hooks()
    _registry_config = config
    logger.info(
        "03_registry started: tables=%s",
        ", ".join(table.id for table in config.tables),
    )
    return config
