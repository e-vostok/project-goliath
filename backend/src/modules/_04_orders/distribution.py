"""
Judge selection algorithm of module 04_orders (Spec 2.5, 3.3).

Pure and synchronous — no I/O, no session, no global state: the service
gathers ``JudgeCandidate`` rows and calls the selector, so tests cover
the ordering rules without a database. ``judge_selector`` is the single
injection point: tests may replace it, everything else stays identical.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from modules._04_orders.config_schema import JudgeSettings


@dataclass(frozen=True)
class JudgeCandidate:
    """One player's eligibility snapshot for judge selection (Spec 2.5)."""

    player_id: str
    has_nation: bool
    consented: bool
    pending: int
    last_assigned_at: datetime | None


JudgeSelector = Callable[[str, Sequence[JudgeCandidate], JudgeSettings], str | None]


def select_judge_v1(
    author_player_id: str,
    candidates: Sequence[JudgeCandidate],
    settings: JudgeSettings,
) -> str | None:
    """
    Pick the judge (Spec 2.5, 3.3): the author is never eligible; the
    load limit is strict; with ``require_reachable`` a candidate needs
    a nation or bot consent. There is no rating threshold — judging
    requires no minimum rating (0.14.0). The winner minimises
    ``(pending, last_assigned_at, player_id)`` — a judge who has never
    been assigned counts as the oldest (τ = −∞). Returns ``None`` when
    the eligible set is empty.
    """
    eligible = [
        c
        for c in candidates
        if c.player_id != author_player_id
        and c.pending < settings.max_pending_verdicts
        and (not settings.require_reachable or c.has_nation or c.consented)
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda c: (
            c.pending,
            # False sorts before True: never-assigned judges win (τ = −∞).
            c.last_assigned_at is not None,
            c.last_assigned_at,
            c.player_id,
        ),
    ).player_id


# Selector injection point: tests replace this reference to check the
# wiring or force NO_CANDIDATES; the rest of distribute() is unchanged.
judge_selector: JudgeSelector = select_judge_v1

# The random source of the overdue-order seizure (0.14.0 unit 7b): the
# worker hands a seized order to a uniformly random administrator via
# ``admin_random.choice``. The instance is the injection point for
# tests, like judge_selector above.
admin_random: random.Random = random.Random()
