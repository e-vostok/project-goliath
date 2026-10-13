"""
Extension registries of module 02_bot (Spec 2.6).

Two registries open the module to satellite modules: notification
types (key + the template variables the owning module promises to
send) and deadline-audience providers. Both are populated at startup —
the bot registers its five builtin types itself — and validated against
``configs/02_bot.yaml`` by :func:`validate_registry_against_config`.
A registered key absent from the YAML, or a template placeholder
outside the registered variables, is startup-fatal
(:class:`BotRegistryError`); a YAML type nobody registered is legal —
it simply waits for its module.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.exceptions import CoreDomainError
from modules._02_bot.config_schema import (
    BUILTIN_TYPE_VARIABLES,
    IMPLICIT_MERGE_VARIABLES,
    BotConfig,
    template_placeholders,
)

logger = logging.getLogger(__name__)


class BotRegistryError(CoreDomainError):
    """
    Startup-fatal registry/config mismatch (Spec 2.6): a registered
    key missing from ``configs/02_bot.yaml``, a re-registration with a
    different variable set, or a template placeholder the owning module
    never promised.
    """

    def __init__(self, message: str):
        super().__init__(message, "BOT_REGISTRY_INVALID")


DeadlineAudienceProvider = Callable[
    [AsyncSession, int], Awaitable[set[str]]
]

_notification_types: dict[str, frozenset[str]] = {}
_deadline_audience_providers: list[DeadlineAudienceProvider] = []


def register_notification_type(
    key: str, variables: Iterable[str]
) -> None:
    """
    Register one notification type's variable set at startup.

    Re-registering the same key with the same variables is a no-op
    (idempotent startup); a different set raises BotRegistryError.
    """
    variables = frozenset(variables)
    existing = _notification_types.get(key)
    if existing is not None:
        if existing == variables:
            return
        raise BotRegistryError(
            f"notification type '{key}' re-registered with a different "
            f"variable set: {sorted(existing)} vs {sorted(variables)}"
        )
    _notification_types[key] = variables


def register_deadline_audience(
    provider: DeadlineAudienceProvider,
) -> None:
    """
    Register a deadline-audience provider (Spec 2.6); several providers
    are OR-ed. Idempotent — the same callable is not added twice.
    """
    if provider not in _deadline_audience_providers:
        _deadline_audience_providers.append(provider)


def register_builtin_types() -> None:
    """Register the five types the bot owns itself (BUILTIN_TYPE_VARIABLES)."""
    for key, variables in BUILTIN_TYPE_VARIABLES.items():
        register_notification_type(key, variables)


def get_notification_type(key: str) -> frozenset[str] | None:
    """The registered variable set of one type, or None."""
    return _notification_types.get(key)


def get_notification_types() -> dict[str, frozenset[str]]:
    """All registered notification types, keyed by type key."""
    return dict(_notification_types)


def get_deadline_audience_providers() -> tuple[DeadlineAudienceProvider, ...]:
    """All registered deadline-audience providers, in order."""
    return tuple(_deadline_audience_providers)


def clear_registry() -> None:
    """Drop every registration — test isolation."""
    _notification_types.clear()
    _deadline_audience_providers.clear()


def validate_registry_against_config(config: BotConfig) -> None:
    """
    Startup check (Spec 2.6): every registered key must exist in
    ``config.types`` and every template placeholder of that type must
    come from the registered variables — with ``count`` additionally
    allowed inside ``batch_text``/``line_text``.
    """
    for key, variables in sorted(_notification_types.items()):
        type_cfg = config.types.get(key)
        if type_cfg is None:
            raise BotRegistryError(
                f"notification type '{key}' is registered but absent "
                "from configs/02_bot.yaml -> types"
            )
        merge_allowed = variables | IMPLICIT_MERGE_VARIABLES
        for field_name, template, allowed in (
            ("text", type_cfg.text, variables),
            ("batch_text", type_cfg.batch_text, merge_allowed),
            ("line_text", type_cfg.line_text, merge_allowed),
        ):
            if template is None:
                continue
            unknown = sorted(set(template_placeholders(template)) - allowed)
            if unknown:
                raise BotRegistryError(
                    f"types.{key}.{field_name}: placeholders {unknown} "
                    "are not in the registered variable set "
                    f"{sorted(allowed)}"
                )
