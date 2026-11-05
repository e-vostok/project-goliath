"""
Judge-rating service of module 00_core (0.14.0 unit 6a).

``change_judge_rating`` is the only write path to
``players.judge_rating``: it clamps the result to the model scale
(``JUDGE_RATING_MIN``..``JUDGE_RATING_MAX``, Spec 03_registry D1),
records one append-only ``judge_rating_log`` row with both the
requested and the applied delta, and is idempotent by ``source_key`` —
a repeated event returns the existing entry and changes nothing. The
player row is taken under ``SELECT ... FOR UPDATE`` so two concurrent
changes can never lose one; the ``source_key`` unique constraint plus a
SAVEPOINT-wrapped insert covers the same key arriving on different
player rows.

``list_judge_rating_log`` reads the journal newest-first for the admin
panel (unit 6b), paging by ``before_id``.

Both functions run inside the caller's transaction and never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.exceptions import (
    PlayerNotFoundError,
    RatingChangeInvalidError,
)
from modules._00_core.models import JudgeRatingLog, Player
from modules._00_core.player_stats import JUDGE_RATING_MAX, JUDGE_RATING_MIN

# The reason codes ck_judge_rating_log_reason_code pins. The three
# ORDER_* penalties arrive with 0.14.0 unit 7a; MANUAL serves the
# admin-panel edit (unit 6b) and always carries a note and an actor.
REASON_MANUAL = "MANUAL"
JUDGE_RATING_REASONS = (
    "ORDER_REFUSED",
    "ORDER_REFUSED_LATE",
    "ORDER_OVERDUE",
    REASON_MANUAL,
)

SOURCE_KEY_MAX_LEN = 120
NOTE_MAX_LEN = 300


@dataclass(frozen=True)
class JudgeRatingChange:
    """The result of ``change_judge_rating``.

    ``created`` is False when ``source_key`` already had an entry — the
    repeat returns that entry's numbers and moves nothing.
    """

    entry_id: int
    rating_before: int
    rating_after: int
    applied_delta: int
    created: bool


@dataclass(frozen=True)
class JudgeRatingLogEntry:
    """One ``judge_rating_log`` row — every column, newest first."""

    id: int
    player_id: str
    delta: int
    applied_delta: int
    rating_before: int
    rating_after: int
    reason_code: str
    note: str | None
    actor_player_id: str | None
    source_key: str
    created_at: datetime


def _entry(row: JudgeRatingLog) -> JudgeRatingLogEntry:
    return JudgeRatingLogEntry(
        id=row.id,
        player_id=row.player_id,
        delta=row.delta,
        applied_delta=row.applied_delta,
        rating_before=row.rating_before,
        rating_after=row.rating_after,
        reason_code=row.reason_code,
        note=row.note,
        actor_player_id=row.actor_player_id,
        source_key=row.source_key,
        created_at=row.created_at,
    )


def _result(row: JudgeRatingLog, created: bool) -> JudgeRatingChange:
    return JudgeRatingChange(
        entry_id=row.id,
        rating_before=row.rating_before,
        rating_after=row.rating_after,
        applied_delta=row.applied_delta,
        created=created,
    )


def _validate(
    delta: int,
    reason_code: str,
    source_key: str,
    note: str | None,
    actor_player_id: str | None,
) -> tuple[str, str | None]:
    """Argument rules of every rating change; returns the cleaned
    ``(source_key, note)``."""
    if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0:
        raise RatingChangeInvalidError("delta must be a non-zero integer")
    if reason_code not in JUDGE_RATING_REASONS:
        raise RatingChangeInvalidError(f"unknown reason_code '{reason_code}'")
    if not isinstance(source_key, str) or not source_key.strip():
        raise RatingChangeInvalidError("source_key must be a non-empty string")
    key = source_key.strip()
    if len(key) > SOURCE_KEY_MAX_LEN:
        raise RatingChangeInvalidError(
            f"source_key is longer than {SOURCE_KEY_MAX_LEN} characters"
        )
    if reason_code == REASON_MANUAL:
        cleaned = note.strip() if isinstance(note, str) else ""
        if not cleaned:
            raise RatingChangeInvalidError("MANUAL requires a non-empty note")
        if len(cleaned) > NOTE_MAX_LEN:
            raise RatingChangeInvalidError(
                f"note is longer than {NOTE_MAX_LEN} characters"
            )
        if not actor_player_id:
            raise RatingChangeInvalidError("MANUAL requires actor_player_id")
        return key, cleaned
    if note is not None:
        raise RatingChangeInvalidError(f"{reason_code} forbids a note")
    if actor_player_id is not None:
        raise RatingChangeInvalidError(f"{reason_code} forbids actor_player_id")
    return key, None


async def change_judge_rating(
    session: AsyncSession,
    player_id: str,
    delta: int,
    reason_code: str,
    source_key: str,
    note: str | None = None,
    actor_player_id: str | None = None,
) -> JudgeRatingChange:
    """
    Apply one rating change and journal it — the only function that
    may write ``players.judge_rating``.

    Idempotent by ``source_key``: an already-recorded key returns its
    existing entry with ``created=False`` and moves nothing.

    Raises:
        RatingChangeInvalidError: a broken argument (zero delta,
            unknown reason, bad source_key, MANUAL without note/actor,
            ORDER_* with either).
        PlayerNotFoundError: the player does not exist.
    """
    key, cleaned_note = _validate(
        delta, reason_code, source_key, note, actor_player_id
    )

    # Lock the player row first: same-player changes serialise here,
    # and the loser of a same-source_key race re-reads the journal only
    # after the winner's row is visible.
    player = (
        await session.execute(
            select(Player).where(Player.id == player_id).with_for_update()
        )
    ).scalar_one_or_none()
    if player is None:
        raise PlayerNotFoundError(player_id)

    existing = (
        await session.execute(
            select(JudgeRatingLog).where(JudgeRatingLog.source_key == key)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _result(existing, created=False)

    rating_before = player.judge_rating
    rating_after = max(
        JUDGE_RATING_MIN, min(JUDGE_RATING_MAX, rating_before + delta)
    )
    applied_delta = rating_after - rating_before
    player.judge_rating = rating_after

    entry = JudgeRatingLog(
        player_id=player_id,
        delta=delta,
        applied_delta=applied_delta,
        rating_before=rating_before,
        rating_after=rating_after,
        reason_code=reason_code,
        note=cleaned_note,
        actor_player_id=actor_player_id,
        source_key=key,
    )
    try:
        # SAVEPOINT (not the caller's transaction): on the unique-key
        # loss the transaction stays usable on both dialects.
        async with session.begin_nested():
            session.add(entry)
            await session.flush()
    except IntegrityError:
        # A concurrent transaction committed this source_key first —
        # the player row lock serialises only same-player races. Undo
        # the stale in-memory rating and answer the winner's entry.
        session.expire(player, ["judge_rating"])
        winner = (
            await session.execute(
                select(JudgeRatingLog).where(JudgeRatingLog.source_key == key)
            )
        ).scalar_one()
        return _result(winner, created=False)

    return _result(entry, created=True)


async def list_judge_rating_log(
    session: AsyncSession,
    player_id: str,
    limit: int,
    before_id: int | None = None,
) -> list[JudgeRatingLogEntry]:
    """
    The player's rating journal, newest first.

    ``before_id`` pages backwards: pass the id of the oldest entry of
    the previous page to get the next-older ``limit`` rows.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise RatingChangeInvalidError("limit must be a positive integer")
    stmt = (
        select(JudgeRatingLog)
        .where(JudgeRatingLog.player_id == player_id)
        .order_by(JudgeRatingLog.id.desc())
        .limit(limit)
    )
    if before_id is not None:
        stmt = stmt.where(JudgeRatingLog.id < before_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [_entry(row) for row in rows]
