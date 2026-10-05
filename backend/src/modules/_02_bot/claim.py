"""
Claim step of the sender (Spec 3.2).

One short transaction per pass, in order: expiry bookkeeping,
attempts exhaustion, ready-row selection (players with a critical row
or a dialog reply first, then oldest), consent/nation re-checks
(INV-B3), re-assembly of previously leased groups (kept only when
every row is still ready — INV-B6), composition of the rest (Spec 3.4
with the sent-history limits), and the lease stamp — new
``group_id``/``random_id``/``lease_token``, ``attempts + 1``,
``lease_until`` — that makes a crash between this commit and the VK
call safe to retry.

``FOR UPDATE SKIP LOCKED`` serialises competing workers on
PostgreSQL; SQLite reads plainly (single-process dialect). The
function never commits — the caller owns the commit boundary
(INV-B7: claim, then VK calls, then the result write).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.service import NationService
from modules._02_bot import consent as consent_mod
from modules._02_bot.composer import (
    ComposedMessage,
    RowView,
    SentHistory,
    compose,
)
from modules._02_bot.config_schema import BotConfig
from modules._02_bot.models import BotOutbox
from modules._02_bot.settings import BotEnv


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for timezone=True columns."""
    return (
        value
        if value.tzinfo is not None
        else value.replace(tzinfo=timezone.utc)
    )


def _row_view(row: BotOutbox) -> RowView:
    return RowView(
        id=row.id,
        type_key=row.type_key,
        kind=row.kind,
        priority=row.priority,
        counts_toward_cap=row.counts_toward_cap,
        created_at=row.created_at,
        not_before=row.not_before,
        next_attempt_at=row.next_attempt_at,
        expires_at=row.expires_at,
        payload=row.payload or {},
    )


@dataclass(frozen=True)
class ClaimedGroup:
    """
    One leased message group handed to the sender.

    ``rows`` carries the snapshots the renderer needs; the lease_token
    is the write-back guard (Spec 3.3 step 4).
    """

    player_id: str
    group_id: str
    random_id: int
    render_mode: str
    type_key: str | None
    counts_toward_cap: bool
    collapsed_counts: tuple[tuple[str, int], ...]
    lease_token: str
    rows: tuple[RowView, ...]

    @property
    def row_ids(self) -> tuple[int, ...]:
        return tuple(row.id for row in self.rows)

    def composed_message(self) -> ComposedMessage:
        """The message as the composer emitted it, for render_message."""
        return ComposedMessage(
            self.row_ids,
            self.render_mode,  # type: ignore[arg-type]
            self.type_key,
            self.counts_toward_cap,
            self.collapsed_counts,
        )


def _ready_condition(now: datetime):
    """Spec 3.2 step 3: PENDING or lease-expired LEASED, due and live."""
    return and_(
        or_(
            BotOutbox.status == "PENDING",
            and_(
                BotOutbox.status == "LEASED",
                or_(
                    BotOutbox.lease_until <= now,
                    BotOutbox.lease_until.is_(None),
                ),
            ),
        ),
        BotOutbox.not_before <= now,
        BotOutbox.next_attempt_at <= now,
        BotOutbox.expires_at > now,
    )


def _new_random_id() -> int:
    """INV-B6: a random 31-bit id per group, never derived from row ids."""
    return secrets.randbelow(2**31 - 1) + 1


async def _sent_history(
    session: AsyncSession,
    player_id: str,
    type_keys: set[str],
    config: BotConfig,
    now: datetime,
) -> SentHistory:
    """The per-player send limits of Spec 3.4, read from bot_outbox."""
    cap_cutoff = now - timedelta(hours=24)
    cap_used = (
        await session.execute(
            select(func.count(func.distinct(BotOutbox.group_id))).where(
                BotOutbox.player_id == player_id,
                BotOutbox.status == "SENT",
                BotOutbox.counts_toward_cap.is_(True),
                BotOutbox.sent_at > cap_cutoff,
            )
        )
    ).scalar_one()

    singles_in_window: dict[str, int] = {}
    last_batch_at: dict[str, datetime] = {}
    for type_key in type_keys:
        type_cfg = config.types.get(type_key)
        if type_cfg is None:
            continue
        window_start = now - timedelta(minutes=type_cfg.window_minutes)
        singles = (
            await session.execute(
                select(func.count(func.distinct(BotOutbox.group_id))).where(
                    BotOutbox.player_id == player_id,
                    BotOutbox.type_key == type_key,
                    BotOutbox.status == "SENT",
                    BotOutbox.render_mode == "SINGLE",
                    BotOutbox.sent_at > window_start,
                )
            )
        ).scalar_one()
        singles_in_window[type_key] = singles
        last_batch = (
            await session.execute(
                select(func.max(BotOutbox.sent_at)).where(
                    BotOutbox.player_id == player_id,
                    BotOutbox.type_key == type_key,
                    BotOutbox.status == "SENT",
                    BotOutbox.render_mode == "BATCH",
                )
            )
        ).scalar_one()
        if last_batch is not None:
            last_batch_at[type_key] = last_batch

    return SentHistory(
        cap_used=cap_used,
        singles_in_window=singles_in_window,
        last_batch_at=last_batch_at,
    )


async def claim_batch(
    session: AsyncSession,
    config: BotConfig,
    env: BotEnv,
    now: datetime,
) -> list[ClaimedGroup]:
    """
    Spec 3.2 claim: returns the leased groups ready for VK calls.

    Runs inside the caller's transaction — the caller commits, then
    sends (INV-B7). ``env`` is part of the signature for symmetry with
    the other sender steps; the claim itself touches only the queue.
    """
    sender = config.sender

    # Step 1 — expiry (LEASED only with an expired lease, INV-B8).
    await session.execute(
        update(BotOutbox)
        .where(
            BotOutbox.expires_at <= now,
            or_(
                BotOutbox.status == "PENDING",
                and_(
                    BotOutbox.status == "LEASED",
                    or_(
                        BotOutbox.lease_until <= now,
                        BotOutbox.lease_until.is_(None),
                    ),
                ),
            ),
        )
        .values(status="EXPIRED")
    )

    # Step 2 — attempts exhausted.
    await session.execute(
        update(BotOutbox)
        .where(
            BotOutbox.status == "PENDING",
            BotOutbox.attempts >= sender.max_attempts,
        )
        .values(status="FAILED", drop_reason="ATTEMPTS_EXHAUSTED")
    )

    # Step 4 — up to claim_batch_size players: critical/REPLY owners
    # first, then by their oldest ready row.
    urgent = func.max(
        case(
            (
                or_(
                    BotOutbox.priority == "critical",
                    BotOutbox.kind == "REPLY",
                ),
                1,
            ),
            else_=0,
        )
    )
    player_rows = await session.execute(
        select(
            BotOutbox.player_id,
            urgent.label("urgent"),
            func.min(BotOutbox.created_at).label("oldest"),
        )
        .where(_ready_condition(now))
        .group_by(BotOutbox.player_id)
        .order_by(urgent.desc(), "oldest")
        .limit(sender.claim_batch_size)
    )
    player_ids = [row[0] for row in player_rows.all()]
    if not player_ids:
        return []

    # Step 5 — lock the ready rows of the chosen players.
    rows_stmt = select(BotOutbox).where(
        _ready_condition(now), BotOutbox.player_id.in_(player_ids)
    )
    if session.bind.dialect.name == "postgresql":
        rows_stmt = rows_stmt.with_for_update(skip_locked=True)
    db_rows = (await session.execute(rows_stmt)).scalars().all()

    rows_by_player: dict[str, list[BotOutbox]] = {pid: [] for pid in player_ids}
    for row in db_rows:
        rows_by_player.setdefault(row.player_id, []).append(row)

    groups: list[ClaimedGroup] = []
    lease_until = now + timedelta(seconds=sender.lease_seconds)

    for player_id in player_ids:
        surviving = await _apply_player_checks(
            session, player_id, rows_by_player.get(player_id, [])
        )
        kept, ungrouped = await _split_kept_groups(
            session, player_id, surviving, now
        )
        for group_rows in kept:
            groups.append(
                _lease_group(session, player_id, group_rows, now, lease_until)
            )
        if ungrouped:
            groups.extend(
                await _compose_and_lease(
                    session, player_id, ungrouped, config, now, lease_until
                )
            )

    return groups


async def _apply_player_checks(
    session: AsyncSession,
    player_id: str,
    rows: list[BotOutbox],
) -> list[BotOutbox]:
    """Step 6 (INV-B3): NOTIFICATION rows need ALLOWED consent and a
    nation; REPLY rows need neither. Drop reasons per Spec 2.4."""
    if not rows:
        return []
    if not any(row.kind == "NOTIFICATION" for row in rows):
        return list(rows)
    allowed = await consent_mod.is_allowed(session, player_id)
    nation = (
        await NationService.player_nation_summary(session, player_id)
        if allowed
        else None
    )
    surviving: list[BotOutbox] = []
    for row in rows:
        if row.kind != "NOTIFICATION":
            surviving.append(row)
        elif not allowed:
            row.status = "DROPPED"
            row.drop_reason = "NO_CONSENT"
        elif nation is None:
            row.status = "DROPPED"
            row.drop_reason = "NO_NATION"
        else:
            surviving.append(row)
    return surviving


async def _split_kept_groups(
    session: AsyncSession,
    player_id: str,
    surviving: list[BotOutbox],
    now: datetime,
) -> tuple[list[list[BotOutbox]], list[BotOutbox]]:
    """
    Step 7: rows already carrying a ``group_id`` rejoin that group when
    every row of it is still ready; a group missing any row dissolves —
    its survivors lose ``group_id``/``random_id``/``render_mode`` and go
    through composition again (fresh ``random_id``, INV-B6).
    """
    by_group: dict[str, list[BotOutbox]] = {}
    ungrouped: list[BotOutbox] = []
    for row in surviving:
        if row.group_id:
            by_group.setdefault(row.group_id, []).append(row)
        else:
            ungrouped.append(row)

    kept: list[list[BotOutbox]] = []
    for group_id, candidate_rows in by_group.items():
        all_rows = (
            (
                await session.execute(
                    select(BotOutbox).where(
                        BotOutbox.player_id == player_id,
                        BotOutbox.group_id == group_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        surviving_ids = {row.id for row in surviving}
        if all(row.id in surviving_ids for row in all_rows):
            candidate_rows.sort(
                key=lambda r: (_aware(r.created_at), r.id)
            )
            kept.append(candidate_rows)
        else:
            for row in candidate_rows:
                row.group_id = None
                row.random_id = None
                row.render_mode = None
            ungrouped.extend(candidate_rows)
    return kept, ungrouped


def _lease_group(
    session: AsyncSession,
    player_id: str,
    rows: list[BotOutbox],
    now: datetime,
    lease_until: datetime,
) -> ClaimedGroup:
    """Lease one already-formed group under a fresh lease_token."""
    lease_token = str(uuid.uuid4())
    for row in rows:
        row.status = "LEASED"
        row.attempts += 1
        row.lease_until = lease_until
        row.lease_token = lease_token
    render_mode = rows[0].render_mode or "SINGLE"
    if render_mode == "SUMMARY":
        # A reclaimed summary approximates collapsed_counts by rows:
        # the original message-per-type split is not persisted, and
        # the common case (collapsed singles) counts rows == messages.
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.type_key] = counts.get(row.type_key, 0) + 1
        collapsed = tuple(counts.items())
        type_key = None
    else:
        collapsed = ()
        type_key = rows[0].type_key
    return ClaimedGroup(
        player_id=player_id,
        group_id=rows[0].group_id or str(uuid.uuid4()),
        random_id=rows[0].random_id or _new_random_id(),
        render_mode=render_mode,
        type_key=type_key,
        counts_toward_cap=rows[0].counts_toward_cap,
        collapsed_counts=collapsed,
        lease_token=lease_token,
        rows=tuple(_row_view(row) for row in rows),
    )


async def _compose_and_lease(
    session: AsyncSession,
    player_id: str,
    rows: list[BotOutbox],
    config: BotConfig,
    now: datetime,
    lease_until: datetime,
) -> list[ClaimedGroup]:
    """Steps 8–9: compose the ungrouped rows and lease each message."""
    sender = config.sender
    views = [_row_view(row) for row in rows]
    history = await _sent_history(
        session,
        player_id,
        {row.type_key for row in rows},
        config,
        now,
    )
    result = compose(views, history, config, now)
    rows_by_id = {row.id: row for row in rows}

    # Deferred rows (over_cap one-batch-per-window) wait for the
    # resume time; rows that fit no message (daily cap shutout) simply
    # stay queued. Both normalise back to PENDING.
    covered = {row_id for m in result.messages for row_id in m.row_ids}
    for row in rows:
        if row.id in result.deferred:
            row.next_attempt_at = result.deferred[row.id]
        if row.id in covered:
            continue
        row.status = "PENDING"
        row.lease_until = None
        row.lease_token = None
        row.group_id = None
        row.random_id = None
        row.render_mode = None

    groups: list[ClaimedGroup] = []
    for message in result.messages:
        group_id = str(uuid.uuid4())
        random_id = _new_random_id()
        lease_token = str(uuid.uuid4())
        group_rows = []
        for row_id in message.row_ids:
            row = rows_by_id[row_id]
            row.status = "LEASED"
            row.attempts += 1
            row.lease_until = lease_until
            row.lease_token = lease_token
            row.group_id = group_id
            row.random_id = random_id
            row.render_mode = message.render_mode
            group_rows.append(row)
        group_rows.sort(key=lambda r: (_aware(r.created_at), r.id))
        groups.append(
            ClaimedGroup(
                player_id=player_id,
                group_id=group_id,
                random_id=random_id,
                render_mode=message.render_mode,
                type_key=message.type_key,
                counts_toward_cap=message.counts_toward_cap,
                collapsed_counts=message.collapsed_counts,
                lease_token=lease_token,
                rows=tuple(_row_view(row) for row in group_rows),
            )
        )
    return groups
