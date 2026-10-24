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
# A player-delete preview hook sees (session, player_id) and returns a
# JSON-able dict fragment of what the module would lose with that player
# (counts only — e.g. {"outbox_rows": 3}); the admin endpoint merges the
# fragments into its fixed-shape response. Read-only, never commits.
PlayerPreviewHook = Callable[[AsyncSession, str], Awaitable[dict]]
# An overview hook sees (session) and returns the module's tiles for the
# panel's «Состояние мира» card — a list of
# {"key": str, "label": str, "value": str, "sort": int} with `value`
# already formatted for display; `sort` defines the merged cross-module
# order. Read-only, never commits.
OverviewHook = Callable[[AsyncSession], Awaitable[list[dict]]]
# A player-info hook sees (session, player_ids) — the internal ids of
# the page being rendered — and returns {player_id: {field: value}}:
# the display columns of the panel's «Игроки» table the module owns
# (e.g. 03_registry's "display_name"). Read-only, never commits.
PlayerInfoHook = Callable[[AsyncSession, list[str]], Awaitable[dict]]
# A player-search hook sees (session, text) and returns the set of
# player ids matching the free-text query in this module's data —
# merged into GET /admin/players's OR-filter with the core fields.
PlayerSearchHook = Callable[[AsyncSession, str], Awaitable[set]]


class AdminRegistry:
    """
    Registry of admin-panel hooks provided by modules.

    Each module registers at most one hook per hook type, keyed by its
    module_slug. The returned dicts preserve insertion order, which defines
    the order the admin panel iterates over modules.
    """

    _reset_hooks: dict[str, ResetHook] = {}
    _state_view_hooks: dict[str, StateViewHook] = {}
    _player_preview_hooks: dict[str, PlayerPreviewHook] = {}
    _overview_hooks: dict[str, OverviewHook] = {}
    # slug -> (info_fn, search_fn|None); the search half is optional.
    _player_info_hooks: dict[
        str, tuple[PlayerInfoHook, PlayerSearchHook | None]
    ] = {}

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
    def register_player_preview(
        cls, module_slug: str, preview_fn: PlayerPreviewHook
    ) -> None:
        """
        Register a player-delete preview hook for a module.

        Args:
            module_slug: The owning module's slug.
            preview_fn: Async function taking (session, player_id) that
                        returns a dict fragment of per-module counts —
                        what deleting this player would remove. Called by
                        the admin panel's delete-preview endpoint.

        Raises:
            ValueError: If a preview hook is already registered for
                        module_slug.
        """
        if module_slug in cls._player_preview_hooks:
            raise ValueError(
                f"Player-preview hook already registered for module '{module_slug}'"
            )
        cls._player_preview_hooks[module_slug] = preview_fn
        logger.info(f"Registered admin player-preview hook for module '{module_slug}'")

    @classmethod
    def register_overview(cls, module_slug: str, overview_fn: OverviewHook) -> None:
        """
        Register an overview hook for a module.

        Args:
            module_slug: The owning module's slug.
            overview_fn: Async function taking (session) that returns a
                         list of tiles {"key", "label", "value", "sort"}
                         for the panel's «Состояние мира» card. Called by
                         the GET /admin/overview endpoint.

        Raises:
            ValueError: If an overview hook is already registered for
                        module_slug.
        """
        if module_slug in cls._overview_hooks:
            raise ValueError(
                f"Overview hook already registered for module '{module_slug}'"
            )
        cls._overview_hooks[module_slug] = overview_fn
        logger.info(f"Registered admin overview hook for module '{module_slug}'")

    @classmethod
    def register_player_info(
        cls,
        module_slug: str,
        info_fn: PlayerInfoHook,
        search_fn: PlayerSearchHook | None = None,
    ) -> None:
        """
        Register a player-info hook for a module.

        Args:
            module_slug: The owning module's slug.
            info_fn: Async function taking (session, player_ids) that
                     returns {player_id: {field: value}} — the module's
                     display columns for the panel's players table.
                     Called by the GET /admin/players endpoint.
            search_fn: Optional async function taking (session, text)
                       that returns the set of player ids matching the
                       free-text query inside this module's data.

        Raises:
            ValueError: If a player-info hook is already registered for
                        module_slug.
        """
        if module_slug in cls._player_info_hooks:
            raise ValueError(
                f"Player-info hook already registered for module '{module_slug}'"
            )
        cls._player_info_hooks[module_slug] = (info_fn, search_fn)
        logger.info(
            f"Registered admin player-info hook for module '{module_slug}'"
        )

    @classmethod
    def get_reset_hooks(cls) -> dict[str, ResetHook]:
        """Return all registered reset hooks in registration order."""
        return dict(cls._reset_hooks)

    @classmethod
    def get_state_view_hooks(cls) -> dict[str, StateViewHook]:
        """Return all registered state-view hooks in registration order."""
        return dict(cls._state_view_hooks)

    @classmethod
    def get_player_preview_hooks(cls) -> dict[str, PlayerPreviewHook]:
        """Return all player-delete preview hooks in registration order."""
        return dict(cls._player_preview_hooks)

    @classmethod
    def get_overview_hooks(cls) -> dict[str, OverviewHook]:
        """Return all registered overview hooks in registration order."""
        return dict(cls._overview_hooks)

    @classmethod
    def get_player_info_hooks(
        cls,
    ) -> dict[str, tuple[PlayerInfoHook, PlayerSearchHook | None]]:
        """All (info_fn, search_fn|None) pairs in registration order."""
        return dict(cls._player_info_hooks)

    @classmethod
    def clear_handlers(cls) -> None:
        """
        Clear all registered hooks.

        This is primarily useful for testing to ensure a clean state.
        """
        cls._reset_hooks.clear()
        cls._state_view_hooks.clear()
        cls._player_preview_hooks.clear()
        cls._overview_hooks.clear()
        cls._player_info_hooks.clear()
