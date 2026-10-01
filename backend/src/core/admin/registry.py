"""
Admin hook registry.

Modules register admin-facing hooks (data resets, state views) under their
module_slug so the admin panel can discover them generically. Mirrors the
TickOrchestrator pattern: class-level state mutated through classmethods,
with clear_handlers() for test isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ResetHook = Callable[[AsyncSession], Awaitable[None]]
StateViewHook = Callable[[AsyncSession], Awaitable[dict]]


class AdminRegistry:
    """
    Registry of admin-panel hooks provided by modules.

    Each module registers at most one hook per hook type, keyed by its
    module_slug. The returned dicts preserve insertion order, which defines
    the order the admin panel iterates over modules.
    """

    _reset_hooks: dict[str, ResetHook] = {}
    _state_view_hooks: dict[str, StateViewHook] = {}

    @classmethod
    def register_reset(cls, module_slug: str, reset_fn: ResetHook) -> None:
        """
        Register a data-reset hook for a module.

        Args:
            module_slug: The owning module's slug.
            reset_fn: Async function taking (session) that wipes the module's
                      state. Called by the admin panel's reset action.

        Raises:
            ValueError: If a reset hook is already registered for module_slug.
        """
        if module_slug in cls._reset_hooks:
            raise ValueError(
                f"Reset hook already registered for module '{module_slug}'"
            )
        cls._reset_hooks[module_slug] = reset_fn
        logger.info(f"Registered admin reset hook for module '{module_slug}'")

    @classmethod
    def register_state_view(cls, module_slug: str, view_fn: StateViewHook) -> None:
        """
        Register a state-view hook for a module.

        Args:
            module_slug: The owning module's slug.
            view_fn: Async function taking (session) that returns a JSON-able
                     dict snapshot of the module's state for the admin panel.

        Raises:
            ValueError: If a state-view hook is already registered for
                        module_slug.
        """
        if module_slug in cls._state_view_hooks:
            raise ValueError(
                f"State-view hook already registered for module '{module_slug}'"
            )
        cls._state_view_hooks[module_slug] = view_fn
        logger.info(f"Registered admin state-view hook for module '{module_slug}'")

    @classmethod
    def get_reset_hooks(cls) -> dict[str, ResetHook]:
        """Return all registered reset hooks in registration order."""
        return dict(cls._reset_hooks)

    @classmethod
    def get_state_view_hooks(cls) -> dict[str, StateViewHook]:
        """Return all registered state-view hooks in registration order."""
        return dict(cls._state_view_hooks)

    @classmethod
    def clear_handlers(cls) -> None:
        """
        Clear all registered hooks.

        This is primarily useful for testing to ensure a clean state.
        """
        cls._reset_hooks.clear()
        cls._state_view_hooks.clear()
