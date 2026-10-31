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
# A nation-delete preview hook sees (session, nation_id) and returns a
# list of {"code": str, "text": str} — one ready Russian sentence per
# consequence the deletion has inside the module's own tables; the
# admin endpoint merges them into its fixed-shape "consequences"
# list. Read-only, never commits.
NationPreviewHook = Callable[[AsyncSession, str], Awaitable[list[dict]]]
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
# A province-info hook sees (session, province_ids) — the ids of the
# page being rendered — and returns {province_id: {field: value}}:
# the module's display columns for the panel's province pickers
# (01_map's "name"). Read-only, never commits.
ProvinceInfoHook = Callable[[AsyncSession, list[int]], Awaitable[dict]]
# A province-search hook sees (session, text) and returns the set of
# province ids matching the free-text query in this module's data —
# merged into GET /admin/provinces's filter.
ProvinceSearchHook = Callable[[AsyncSession, str], Awaitable[set]]


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
    _nation_preview_hooks: dict[str, NationPreviewHook] = {}
    _overview_hooks: dict[str, OverviewHook] = {}
    # slug -> (info_fn, search_fn|None); the search half is optional.
    _player_info_hooks: dict[str, tuple[PlayerInfoHook, PlayerSearchHook | None]] = {}
    # slug -> (info_fn, search_fn|None) — the province twin of the
    # player-info pair.
    _province_info_hooks: dict[
        str, tuple[ProvinceInfoHook, ProvinceSearchHook | None]
    ] = {}
    # slug -> {action_code: Russian label} — audit rows carry the
    # machine code; the journal screen renders the label of the module
    # that owns the action. A code nobody registered is shown raw.
    _audit_action_hooks: dict[str, dict[str, str]] = {}

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
    def register_nation_preview(
        cls, module_slug: str, preview_fn: NationPreviewHook
    ) -> None:
        """
        Register a nation-delete preview hook for a module.

        Args:
            module_slug: The owning module's slug.
            preview_fn: Async function taking (session, nation_id) that
                        returns a list of {"code", "text"} consequence
                        lines — what deleting this nation would do to
                        the module's own data. Called by the admin
                        panel's nation delete-preview endpoint.

        Raises:
            ValueError: If a preview hook is already registered for
                        module_slug.
        """
        if module_slug in cls._nation_preview_hooks:
            raise ValueError(
                f"Nation-preview hook already registered for module '{module_slug}'"
            )
        cls._nation_preview_hooks[module_slug] = preview_fn
        logger.info(f"Registered admin nation-preview hook for module '{module_slug}'")

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
        logger.info(f"Registered admin player-info hook for module '{module_slug}'")

    @classmethod
    def register_province_info(
        cls,
        module_slug: str,
        info_fn: ProvinceInfoHook,
        search_fn: ProvinceSearchHook | None = None,
    ) -> None:
        """
        Register a province-info hook for a module.

        Args:
            module_slug: The owning module's slug.
            info_fn: Async function taking (session, province_ids) that
                     returns {province_id: {field: value}} — the module's
                     display columns for the panel's province pickers
                     (e.g. 01_map's "name"). Called by the
                     GET /admin/provinces endpoint.
            search_fn: Optional async function taking (session, text)
                       that returns the set of province ids matching the
                       free-text query inside this module's data.

        Raises:
            ValueError: If a province-info hook is already registered for
                        module_slug.
        """
        if module_slug in cls._province_info_hooks:
            raise ValueError(
                f"Province-info hook already registered for module '{module_slug}'"
            )
        cls._province_info_hooks[module_slug] = (info_fn, search_fn)
        logger.info(f"Registered admin province-info hook for module '{module_slug}'")

    @classmethod
    def register_audit_actions(cls, module_slug: str, actions: dict[str, str]) -> None:
        """
        Register the Russian labels of a module's audit action codes.

        Args:
            module_slug: The owning module's slug.
            actions: {action_code: label} — the codes the module writes
                     into admin_audit_log.action and how the panel's
                     «Журнал» names them (e.g. "tick.run" ->
                     "Запуск хода").

        Raises:
            ValueError: If audit actions are already registered for
                        module_slug.
        """
        if module_slug in cls._audit_action_hooks:
            raise ValueError(
                f"Audit actions already registered for module '{module_slug}'"
            )
        cls._audit_action_hooks[module_slug] = dict(actions)
        logger.info(f"Registered admin audit actions for module '{module_slug}'")

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
    def get_nation_preview_hooks(cls) -> dict[str, NationPreviewHook]:
        """Return all nation-delete preview hooks in registration order."""
        return dict(cls._nation_preview_hooks)

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
    def get_province_info_hooks(
        cls,
    ) -> dict[str, tuple[ProvinceInfoHook, ProvinceSearchHook | None]]:
        """All (info_fn, search_fn|None) pairs in registration order."""
        return dict(cls._province_info_hooks)

    @classmethod
    def get_audit_action_hooks(cls) -> dict[str, dict[str, str]]:
        """All {slug: {action_code: label}} maps in registration order."""
        return {
            slug: dict(actions) for slug, actions in cls._audit_action_hooks.items()
        }

    @classmethod
    def get_audit_action_labels(cls) -> dict[str, str]:
        """The merged {action_code: label} map in registration order."""
        labels: dict[str, str] = {}
        for actions in cls._audit_action_hooks.values():
            labels.update(actions)
        return labels

    @classmethod
    def audit_action_label(cls, action: str) -> str:
        """The registered label of an action code; the code itself when unknown."""
        return cls.get_audit_action_labels().get(action, action)

    @classmethod
    def clear_handlers(cls) -> None:
        """
        Clear all registered hooks.

        This is primarily useful for testing to ensure a clean state.
        """
        cls._reset_hooks.clear()
        cls._state_view_hooks.clear()
        cls._player_preview_hooks.clear()
        cls._nation_preview_hooks.clear()
        cls._overview_hooks.clear()
        cls._player_info_hooks.clear()
        cls._province_info_hooks.clear()
        cls._audit_action_hooks.clear()
