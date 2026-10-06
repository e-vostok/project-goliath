"""
Extension-point registries owned by 00_core (Spec 01_map Part 2
"Изменения 00_core").

00_core must never import a satellite module, so satellites hook into
core operations through two small registries populated at startup:

1. **Ownership listeners** — notified when ``provinces.nation_id``
   changes. ``NationService.create`` (claiming provinces) and
   ``NationService.delete`` (releasing them) call
   :func:`notify_ownership_changed` with the list of
   :class:`OwnershipChange` inside the SAME database transaction, before
   the caller commits: a raising listener rolls back the whole operation
   — no owner change, no listener side effects (INV-M7). Every future
   operation that writes ``provinces.nation_id`` (conquest, transfer,
   release) MUST go through this function — it is the single point where
   ownership history is announced. The admin world reset is the
   deliberate exception: it wipes the entire world (and the ownership
   journal itself is cleared via the module's registered reset hook),
   so per-province notification there would be meaningless.

2. **Registration checks** — satellite checks injected into
   ``NationService.create`` at named stages of the Spec Part 5 order:
   ``before_all`` runs first, before any write and before the province
   set is even loaded (its checks receive ``player_id``, not the
   provinces); ``after_free`` runs right after province
   existence/freedom, before the province-count check; ``after_count``
   runs right after it, before the nation row is written. A check
   raises a domain error carrying ``code``/``message`` to reject the
   registration.

Both registries are keyed by name; re-registering the same name replaces
the entry, so application startup stays idempotent across repeated
lifespan boots in one process. Call order is registration order.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from modules._00_core.models import Province

logger = logging.getLogger(__name__)

CheckStage = Literal["before_all", "after_free", "after_count"]
STAGE_BEFORE_ALL: CheckStage = "before_all"
STAGE_AFTER_FREE: CheckStage = "after_free"
STAGE_AFTER_COUNT: CheckStage = "after_count"
_CHECK_STAGES: tuple[CheckStage, ...] = (
    STAGE_BEFORE_ALL,
    STAGE_AFTER_FREE,
    STAGE_AFTER_COUNT,
)


@dataclass(frozen=True)
class OwnershipChange:
    """
    One province's owner change, announced to all listeners.

    ``prev_nation_id`` is the previous owner's id (None when the
    province was free). ``new_nation_id``/``new_name``/``new_color``
    describe the new owner at the moment of the event — all three None
    for a release. ``turn`` is ``game_clock.current_turn`` of the
    transaction performing the change.
    """

    province_id: int
    prev_nation_id: str | None
    new_nation_id: str | None
    new_name: str | None
    new_color: str | None
    turn: int


OwnershipListener = Callable[
    [AsyncSession, Sequence[OwnershipChange]], Awaitable[None]
]

# A check receives the already-loaded province rows (existence and
# freedom were verified by core before any stage runs) and raises a
# domain error carrying ``code``/``message`` to reject the registration.
RegistrationCheck = Callable[
    [AsyncSession, Sequence["Province"]], Awaitable[None]
]
# STAGE_BEFORE_ALL checks run before the provinces are loaded, so they
# see the registering player instead: signature ``(session, player_id)``.
BeforeAllCheck = Callable[[AsyncSession, str], Awaitable[None]]

_ownership_listeners: dict[str, OwnershipListener] = {}
_registration_checks: dict[
    CheckStage, dict[str, RegistrationCheck | BeforeAllCheck]
] = {stage: {} for stage in _CHECK_STAGES}


def register_ownership_listener(
    name: str, listener: OwnershipListener
) -> None:
    """
    Register ``listener`` under ``name``; the same name re-registers
    (replaces) instead of raising — startup is re-run per lifespan boot.
    """
    if name in _ownership_listeners:
        logger.info("Replacing ownership listener '%s'", name)
    _ownership_listeners[name] = listener
    logger.info("Registered ownership listener '%s'", name)


def get_ownership_listeners() -> dict[str, OwnershipListener]:
    """All ownership listeners, keyed by name, in registration order."""
    return dict(_ownership_listeners)


def register_registration_check(
    stage: CheckStage,
    name: str,
    check: RegistrationCheck | BeforeAllCheck,
) -> None:
    """
    Register a nation-registration check for ``stage`` under ``name``;
    re-registering the same name replaces it (idempotent startup).
    """
    if stage not in _registration_checks:
        raise ValueError(f"Unknown registration check stage '{stage}'")
    _registration_checks[stage][name] = check
    logger.info("Registered registration check '%s' at stage '%s'", name, stage)


def get_registration_checks(
    stage: CheckStage,
) -> dict[str, RegistrationCheck | BeforeAllCheck]:
    """Checks of one stage, keyed by name, in registration order."""
    return dict(_registration_checks[stage])


async def notify_ownership_changed(
    session: AsyncSession, changes: Sequence[OwnershipChange]
) -> None:
    """
    Announce province ownership changes to every registered listener.

    The ONLY way an ownership change becomes visible to satellites —
    every writer of ``provinces.nation_id`` must call this inside the
    same transaction as the mutation (INV-M7). A raising listener aborts
    the whole operation; the caller's transaction rolls everything back.
    """
    for name, listener in _ownership_listeners.items():
        try:
            await listener(session, changes)
        except Exception:
            logger.exception("Ownership listener '%s' failed", name)
            raise


async def run_registration_checks(
    stage: CheckStage,
    session: AsyncSession,
    provinces: Sequence["Province"],
) -> None:
    """Run all checks of one province stage, in registration order."""
    if stage == STAGE_BEFORE_ALL:
        raise ValueError(
            "STAGE_BEFORE_ALL checks take (session, player_id) — "
            "run them via run_before_all_checks"
        )
    for check in _registration_checks[stage].values():
        await check(session, provinces)


async def run_before_all_checks(
    session: AsyncSession,
    player_id: str,
) -> None:
    """Run all ``before_all`` checks, in registration order.

    These checks receive ``(session, player_id)``: the stage fires
    before any registration write and before the province set exists.
    """
    for check in _registration_checks[STAGE_BEFORE_ALL].values():
        await check(session, player_id)


def clear_ownership_listeners() -> None:
    """Drop all listeners — test isolation, mirrors clear_handlers()."""
    _ownership_listeners.clear()


def clear_registration_checks() -> None:
    """Drop all registration checks of every stage — test isolation."""
    for checks in _registration_checks.values():
        checks.clear()


def snapshot_extension_points() -> tuple[
    dict[str, OwnershipListener],
    dict[CheckStage, dict[str, RegistrationCheck | BeforeAllCheck]],
]:
    """Opaque snapshot of both registries for test isolation fixtures."""
    return (
        dict(_ownership_listeners),
        {stage: dict(checks) for stage, checks in _registration_checks.items()},
    )


def restore_extension_points(snapshot) -> None:
    """Restore a snapshot taken by :func:`snapshot_extension_points`."""
    listeners, checks = snapshot
    _ownership_listeners.clear()
    _ownership_listeners.update(listeners)
    for stage in _CHECK_STAGES:
        _registration_checks[stage].clear()
        _registration_checks[stage].update(checks.get(stage, {}))
