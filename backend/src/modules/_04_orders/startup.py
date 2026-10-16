"""
Startup wiring of module 04_orders (Spec D11, 2.5).

Two entry points, deliberately split:

- ``register_orders_extensions()`` — registers the Registry table
  source ``orders`` and the four bot notification types (Appendix C:
  the two produced by the assignment now, the reminder and the verdict
  announcement for Issues 7 and 9). Called in ``lifespan`` strictly
  before ``startup_bot()`` and ``startup_registry()``: both validate
  their registries against their configs at boot, so the extensions
  must exist first. Idempotent — ``register_table_source`` replaces a
  repeated key and ``register_notification_type`` accepts a repeated
  identical set.
- ``startup_orders()`` — after every other ``startup_*``: loads and
  validates ``configs/04_orders.yaml`` (a broken YAML stops the boot),
  snapshots the VK-article allowed hosts of ``00_core`` once (Spec D7)
  and registers the admin hooks. The background worker arrives with
  Issue 9 and starts separately.

Both the config and the allowed hosts are kept in module-level holders
for ``get_orders_config()`` / ``get_orders_allowed_hosts()`` — neither
the service nor the rules re-read YAML per request.
"""

from __future__ import annotations

import logging

from modules._00_core.profile_rules import history_url_allowed_hosts
from modules._02_bot.registry import register_notification_type
from modules._03_registry.registry import register_table_source
from modules._04_orders.admin_hooks import register_orders_admin_hooks
from modules._04_orders.config_schema import OrdersConfig
from modules._04_orders.notifications import NOTIFICATION_VARIABLES
from modules._04_orders.registry_source import (
    ORDERS_PROVIDES,
    load_orders_rows,
)

logger = logging.getLogger(__name__)

_orders_config: OrdersConfig | None = None
_orders_allowed_hosts: tuple[str, ...] | None = None


def get_orders_config() -> OrdersConfig:
    """The config loaded by :func:`startup_orders`; raises before it ran."""
    if _orders_config is None:
        raise RuntimeError(
            "OrdersConfig is not loaded — startup_orders() has not run"
        )
    return _orders_config


def get_orders_allowed_hosts() -> tuple[str, ...]:
    """The VK-article host list snapshotted by :func:`startup_orders`."""
    if _orders_allowed_hosts is None:
        raise RuntimeError(
            "orders allowed hosts not loaded — startup_orders() has not run"
        )
    return _orders_allowed_hosts


def register_orders_extensions() -> None:
    """
    Register the module's extension points before the owning modules'
    startups validate them (Spec D11): the Registry table source and the
    four ORDER_* bot notification types with their variable sets
    (Appendix C). Reminder and verdict types are registration-only for
    now — their producers arrive with Issues 7 and 9.
    """
    register_table_source("orders", ORDERS_PROVIDES, load_orders_rows)
    for key, variables in NOTIFICATION_VARIABLES.items():
        register_notification_type(key, variables)


def startup_orders() -> OrdersConfig:
    """Boot the module's static parts; returns the validated config."""
    global _orders_config, _orders_allowed_hosts
    config = OrdersConfig.from_yaml(OrdersConfig.get_default_config_path())
    _orders_allowed_hosts = history_url_allowed_hosts()
    register_orders_admin_hooks()
    _orders_config = config
    logger.info("04_orders started")
    return config
