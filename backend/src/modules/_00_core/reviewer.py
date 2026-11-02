"""
Reviewer selection algorithm of module 00_core (Spec applications §5).

Pure and synchronous — no I/O, no session, no global state: the
application service gathers ``ReviewerCandidate`` rows and calls the
selector, so tests cover the ordering rules without a database.
``reviewer_selector`` is the single injection point: tests may replace
it, everything else stays identical. Mirrors ``select_judge_v1`` of
module 04_orders.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReviewerCandidate:
    """One administrator's eligibility snapshot for reviewer
    selection (Spec applications §5). Only administrators with a
    ``players`` row reach this list — env allowlist plus grants."""

    player_id: str
    # Applications currently PENDING that name this reviewer.
    pending: int
    # reviewer_assigned_at of this reviewer's last application —
    # None means never assigned (counts as the oldest, τ = −∞).
    last_assigned_at: datetime | None


ReviewerSelector = Callable[[str, Sequence[ReviewerCandidate]], str | None]


def select_reviewer_v1(
    applicant_player_id: str,
    candidates: Sequence[ReviewerCandidate],
) -> str | None:
    """
    Pick the reviewer (Spec applications §5): the applicant is never
    eligible. The winner minimises ``(pending, last_assigned_at,
    player_id)`` — a reviewer who has never been assigned counts as
    the oldest (τ = −∞). Returns ``None`` when the eligible set is
    empty — the application then waits for its deadline or a later
    assignment pass.
    """
    eligible = [c for c in candidates if c.player_id != applicant_player_id]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda c: (
            c.pending,
            # False sorts before True: never-assigned reviewers win (τ = −∞).
            c.last_assigned_at is not None,
            c.last_assigned_at,
            c.player_id,
        ),
    ).player_id


# Selector injection point: tests replace this reference to check the
# wiring or force an empty pick; the rest of the flow is unchanged.
reviewer_selector: ReviewerSelector = select_reviewer_v1
