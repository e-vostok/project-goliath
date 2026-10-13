"""
Message composition of module 02_bot (Spec 3.4) — pure functions.

No database, no clock reads: rows arrive as :class:`RowView` snapshots
of one player's ready rows, the send history as :class:`SentHistory`,
and ``now`` is injected. The claim step turns the output into leased
groups: :attr:`ComposeResult.messages` are what gets rendered and sent;
:attr:`ComposeResult.deferred` maps row ids to the resume time imposed
by the one-batch-per-window rule.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from modules._02_bot.config_schema import BotConfig


def _utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


def _age_key(row: "RowView") -> tuple[datetime, int]:
    """Age ordering: oldest row first, id breaks ties deterministically."""
    return (_utc(row.created_at), row.id)


@dataclass(frozen=True)
class RowView:
    """A ``bot_outbox`` row as the composer sees it."""

    id: int
    type_key: str
    kind: str
    priority: str
    counts_toward_cap: bool
    created_at: datetime
    not_before: datetime
    next_attempt_at: datetime
    expires_at: datetime
    payload: Mapping[str, object]


@dataclass(frozen=True)
class SentHistory:
    """
    What was already sent to this player, for the limits of Spec 3.4:

    - ``cap_used`` — messages sent in the sliding 24h window that
      counted toward the daily cap (distinct sent ``group_id``s);
    - ``singles_in_window`` — per type, SINGLE messages sent within
      the type's ``window_minutes``;
    - ``last_batch_at`` — per type, the last BATCH send time.
    """

    cap_used: int
    singles_in_window: Mapping[str, int] = field(default_factory=dict)
    last_batch_at: Mapping[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class ComposedMessage:
    """
    One outgoing VK message: the rows it carries and how they render.

    ``collapsed_counts`` is set only for ``SUMMARY``: pairs of
    (type_key, number of collapsed messages of the type), oldest type
    first — ``line_text``'s ``{count}`` counts collapsed *messages*,
    not rows (Spec 3.4, step 3).
    """

    row_ids: tuple[int, ...]
    render_mode: Literal["SINGLE", "BATCH", "SUMMARY"]
    type_key: str | None
    counts_toward_cap: bool
    collapsed_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ComposeResult:
    messages: list[ComposedMessage]
    deferred: dict[int, datetime]


def compose(
    rows: Sequence[RowView],
    history: SentHistory,
    config: BotConfig,
    now: datetime,
) -> ComposeResult:
    """
    Spec 3.4: one player's ready rows -> messages + deferred rows.

    Rows not yet ready (``not_before``/``next_attempt_at`` in the
    future) or already expired (``expires_at <= now``) are ignored.
    """
    ready = [
        row
        for row in rows
        if _utc(row.not_before) <= now
        and _utc(row.next_attempt_at) <= now
        and _utc(row.expires_at) > now
    ]
    rows_by_id = {row.id: row for row in ready}

    # Step 1: critical rows and dialog replies are single messages,
    # never in the daily cap and never merged.
    critical = sorted(
        (r for r in ready if r.priority == "critical"), key=_age_key
    )
    replies = sorted(
        (
            r
            for r in ready
            if r.kind == "REPLY" and r.priority != "critical"
        ),
        key=_age_key,
    )
    head = [
        ComposedMessage(
            (row.id,), "SINGLE", row.type_key, counts_toward_cap=False
        )
        for row in critical
    ] + [
        ComposedMessage(
            (row.id,), "SINGLE", row.type_key, counts_toward_cap=False
        )
        for row in replies
    ]

    # Step 2: merge normal notification rows per type.
    normal = [
        r
        for r in ready
        if r.priority != "critical" and r.kind == "NOTIFICATION"
    ]
    by_type: dict[str, list[RowView]] = {}
    for row in normal:
        by_type.setdefault(row.type_key, []).append(row)

    deferred: dict[int, datetime] = {}
    rest: list[ComposedMessage] = []
    for type_key, type_rows in by_type.items():
        type_rows.sort(key=_age_key)
        type_cfg = config.types.get(type_key)
        merge = type_cfg.merge if type_cfg is not None else "never"
        counts_toward_cap = type_rows[0].counts_toward_cap

        if merge == "never":
            rest.extend(
                ComposedMessage(
                    (row.id,), "SINGLE", type_key, counts_toward_cap
                )
                for row in type_rows
            )
        elif merge == "always":
            if len(type_rows) == 1:
                rest.append(
                    ComposedMessage(
                        (type_rows[0].id,),
                        "SINGLE",
                        type_key,
                        counts_toward_cap,
                    )
                )
            else:
                rest.append(
                    ComposedMessage(
                        tuple(row.id for row in type_rows),
                        "BATCH",
                        type_key,
                        counts_toward_cap,
                    )
                )
        else:  # "over_cap"
            singles_in_window = history.singles_in_window.get(type_key, 0)
            free = max(0, type_cfg.max_per_window - singles_in_window)
            single_rows = type_rows[:free]
            remainder = type_rows[free:]
            rest.extend(
                ComposedMessage(
                    (row.id,), "SINGLE", type_key, counts_toward_cap
                )
                for row in single_rows
            )
            if remainder:
                window = timedelta(minutes=type_cfg.window_minutes)
                last_batch = history.last_batch_at.get(type_key)
                if (
                    last_batch is not None
                    and _utc(last_batch) + window > now
                ):
                    resume = _utc(last_batch) + window
                    for row in remainder:
                        deferred[row.id] = resume
                else:
                    rest.append(
                        ComposedMessage(
                            tuple(row.id for row in remainder),
                            "BATCH",
                            type_key,
                            counts_toward_cap,
                        )
                    )

    def _oldest_row_age(message: ComposedMessage) -> tuple[datetime, int]:
        return min(_age_key(rows_by_id[i]) for i in message.row_ids)

    rest.sort(key=_oldest_row_age)

    # Step 3: daily cap — only messages with counts_toward_cap play.
    free_slots = max(0, config.limits.daily_cap_normal - history.cap_used)
    capped = [m for m in rest if m.counts_toward_cap]
    passing = [m for m in rest if not m.counts_toward_cap]
    if len(capped) <= free_slots:
        passing.extend(capped)
    elif free_slots >= 1:
        passing.extend(capped[: free_slots - 1])
        collapsed = capped[free_slots - 1 :]
        collapsed_ids = sorted(
            (i for m in collapsed for i in m.row_ids),
            key=lambda i: _age_key(rows_by_id[i]),
        )
        counts: dict[str, int] = {}
        oldest_by_type: dict[str, tuple[datetime, int]] = {}
        for m in collapsed:
            counts[m.type_key] = counts.get(m.type_key, 0) + 1
            oldest = min(_age_key(rows_by_id[i]) for i in m.row_ids)
            if (
                m.type_key not in oldest_by_type
                or oldest < oldest_by_type[m.type_key]
            ):
                oldest_by_type[m.type_key] = oldest
        ordered_types = sorted(counts, key=oldest_by_type.__getitem__)
        passing.append(
            ComposedMessage(
                tuple(collapsed_ids),
                "SUMMARY",
                None,
                counts_toward_cap=True,
                collapsed_counts=tuple(
                    (k, counts[k]) for k in ordered_types
                ),
            )
        )
    # free_slots == 0: none of the capped messages go, none deferred —
    # they simply wait for the next pass (Spec 3.4, a = 0).

    passing.sort(key=_oldest_row_age)
    return ComposeResult(messages=head + passing, deferred=deferred)
