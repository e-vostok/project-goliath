"""
Domain services for module 00_core.

Provides business logic for Player, Nation, and ScheduledAction entities.
Enforces all invariants defined in the system specification.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules._00_core.color_policy import oklab_distance
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    CapitalNotInProvincesError,
    ColorTakenError,
    ColorTooCloseError,
    FlagInvalidError,
    FrequencyCapExceededError,
    NameTakenError,
    NationAlreadyExistsError,
    NationNotFoundError,
    PlayerNotFoundError,
    PortraitInvalidError,
    ProvinceCountOutOfRangeError,
    ProvinceNotFoundError,
    ProvinceTakenError,
    RetiredProvinceHistoryError,
    RetiredProvinceOwnedError,
    ShortNameTakenError,
)
from modules._00_core.hooks import (
    STAGE_AFTER_COUNT,
    STAGE_AFTER_FREE,
    OwnershipChange,
    get_player_delete_hooks,
    notify_ownership_changed,
    run_before_all_checks,
    run_nation_created_hooks,
    run_registration_checks,
)
from modules._00_core.models import (
    GameClock,
    Nation,
    Player,
    Province,
    ScheduledAction,
    ScheduledActionStatus,
)
from modules._00_core.profile_rules import (
    validate_anthem_url,
    validate_capital_name,
    validate_description,
    validate_flag_id,
    validate_gender,
    validate_history_url,
    validate_leader_bio,
    validate_leader_name,
    validate_leader_title,
    validate_motto,
    validate_portrait_id,
    validate_short_name,
    validate_succession_type,
)

if TYPE_CHECKING:
    pass


# PostgreSQL advisory-lock key serializing nation registrations and
# color checks across every process sharing the database ('NATIONS' as
# ASCII hex). Must fit bigint; no-op dialects (SQLite) skip it — the
# single writer needs no lock (Spec Part 2 "Ключ блокировки").
NATIONS_ADVISORY_LOCK_KEY = 0x4E4154494F4E53


class FrequencyRule(str):
    """Frequency rules for scheduled actions."""

    ONCE_PER_TURN = "ONCE_PER_TURN"
    ONCE_PER_GAME = "ONCE_PER_GAME"
    MULTIPLE_PER_TURN = "MULTIPLE_PER_TURN"
    UNLIMITED = "UNLIMITED"


ProvinceKind = Literal["LAND", "SEA"]


@dataclass(frozen=True)
class NodeSpec:
    """One map node from manifest.json: an id and its kind."""

    id: int
    kind: ProvinceKind


@dataclass(frozen=True)
class EnsureNodesResult:
    """Outcome of ProvinceService.ensure_nodes (all lists sorted)."""

    added: list[int] = field(default_factory=list)
    kind_mismatch: list[int] = field(default_factory=list)
    extra_in_db: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class RetiredRemovalResult:
    """Outcome of ProvinceService.remove_retired (all lists sorted)."""

    removed: list[int] = field(default_factory=list)
    absent: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class OwnedProvinceInfo:
    """
    One currently-owned province with its nation's display fields —
    the read shape ``/map/state`` (01_map) needs for the live turn.
    """

    province_id: int
    nation_id: str
    nation_name: str
    nation_color: str
    nation_short_name: str


@dataclass(frozen=True)
class PlayerNationSummary:
    """
    The player's nation as satellites need it (Spec 02_bot Part 1.3):
    display fields plus the province count — enough for digests and
    the "has nation" check. ``leader_name``/``leader_title`` may be
    None for nations predating the profile migration. ``flag_id`` is
    None for nations created before 0.9.0.
    """

    nation_id: str
    name: str
    leader_name: str | None
    leader_title: str | None
    province_count: int
    color_hex: str
    short_name: str
    flag_id: str | None = None


@dataclass(frozen=True)
class GameClockSnapshot:
    """The whole ``game_clock`` row, detached, for satellites."""

    current_turn: int
    last_tick_at: datetime | None
    next_tick_at: datetime | None


@dataclass(frozen=True)
class PlayerRegistryRow:
    """
    One players-table row for module 03_registry (Spec 03_registry 1.4).

    ``player_id``/``vk_user_id`` are read plumbing for the module and the
    profile worker — they never reach the client (INV-R2).
    """

    player_id: str
    vk_user_id: int
    created_at: datetime
    level: int
    judge_rating: int
    nation_id: str | None
    nation_name: str | None
    nation_color: str | None
    # A nation's short_name is never NULL (migration 0012); None here
    # only means "the player owns no nation", like the other nation_*
    # fields. flag_id is a catalog id (NULL for pre-0.9.0 nations).
    nation_short_name: str
    nation_flag_id: str | None = None


@dataclass(frozen=True)
class NationRegistryRow:
    """
    One nations-table row for module 03_registry (Spec 03_registry 1.4,
    Spec 00_core Appendix A1). ``short_name`` is never NULL (NOT NULL
    since migration 0012); ``flag_id`` is None for nations created
    before 0.9.0.
    """

    nation_id: str
    name: str
    color_hex: str
    created_turn: int
    created_at: datetime
    province_count: int
    short_name: str
    flag_id: str | None = None


ColorStatus = Literal["OK", "TAKEN", "TOO_CLOSE"]


class ProvinceService:
    """Service for the provinces table (map nodes)."""

    @staticmethod
    async def ensure_nodes(
        session: AsyncSession,
        nodes: Sequence[NodeSpec],
    ) -> EnsureNodesResult:
        """
        Insert missing provinces for the given map nodes (INV-M5 helper).

        Only inserts rows that do not exist yet (nation_id NULL); never
        updates or deletes. Idempotent: a second call adds nothing. Runs
        inside the caller's transaction — this method never commits.

        Args:
            session: The async database session.
            nodes: Node specs (id + kind) from manifest.json.

        Returns:
            EnsureNodesResult with the ids that were inserted, the ids
            whose existing row has a different kind (left unchanged), and
            ids present in the DB but absent from `nodes` (not removed) —
            the caller decides whether extra rows are fatal (INV-M5).

        Raises:
            ValueError: On duplicate ids or an invalid kind in `nodes`;
                nothing is written in that case.
        """
        ids = [node.id for node in nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate node ids in input")
        invalid_kinds = {node.kind for node in nodes} - {"LAND", "SEA"}
        if invalid_kinds:
            raise ValueError(f"Invalid node kinds in input: {sorted(invalid_kinds)}")

        result = await session.execute(select(Province.id, Province.kind))
        existing = {row.id: row.kind for row in result.all()}

        spec_by_id = {node.id: node.kind for node in nodes}
        added = sorted(set(spec_by_id) - set(existing))
        kind_mismatch = sorted(
            node_id
            for node_id in set(spec_by_id) & set(existing)
            if existing[node_id] != spec_by_id[node_id]
        )
        extra_in_db = sorted(set(existing) - set(spec_by_id))

        if added:
            await session.execute(
                insert(Province),
                [{"id": node_id, "kind": spec_by_id[node_id]} for node_id in added],
            )

        return EnsureNodesResult(
            added=added,
            kind_mismatch=kind_mismatch,
            extra_in_db=extra_in_db,
        )

    @staticmethod
    async def remove_retired(
        session: AsyncSession,
        retired_ids: Sequence[int],
        history_ids: Iterable[int] = frozenset(),
    ) -> RetiredRemovalResult:
        """
        Delete the ``provinces`` rows of retired map nodes (INV-M5, 1.9).

        ``retired_ids`` are ids present in ``ids.lock.json`` but absent
        from ``manifest.json`` — nodes taken out of the game by the map
        pipeline. A row that exists and is unowned is deleted; one that
        is owned aborts startup with :class:`RetiredProvinceOwnedError`
        naming the provinces and their nations.

        ``history_ids`` is the subset of ``retired_ids`` that still carry
        ``map_ownership_log`` rows — probed by the caller through the
        journal's own module (data sovereignty). Deleting such a row
        would either violate the FK (PostgreSQL) or orphan the append-only
        journal (SQLite), so it aborts startup with
        :class:`RetiredProvinceHistoryError` instead; the journal is never
        touched.

        Runs inside the caller's transaction — this method never commits.
        The journal is not modified (INV-M7; the rows are history).
        """
        ids = set(retired_ids)
        if not ids:
            return RetiredRemovalResult()
        history = set(history_ids) & ids

        result = await session.execute(
            select(Province.id, Province.nation_id, Nation.name)
            .outerjoin(Nation, Province.nation_id == Nation.id)
            .where(Province.id.in_(ids))
            .order_by(Province.id)
        )
        rows = result.all()
        present = {row[0] for row in rows}

        owned = [(row[0], row[1], row[2]) for row in rows if row[1] is not None]
        if owned:
            raise RetiredProvinceOwnedError(owned)
        blocked = sorted(present & history)
        if blocked:
            raise RetiredProvinceHistoryError(blocked)

        removable = sorted(present)
        if removable:
            await session.execute(delete(Province).where(Province.id.in_(removable)))
        return RetiredRemovalResult(
            removed=removable,
            absent=sorted(ids - present),
        )

    @staticmethod
    async def list_current_owners(
        session: AsyncSession,
    ) -> list[OwnedProvinceInfo]:
        """
        Every owned province joined to its nation, ordered by province
        id — the public read path for satellites (e.g. /map/state).

        Read-only and never commits. Sea zones cannot appear:
        ck_provinces_sea_unowned keeps their nation_id NULL.
        """
        result = await session.execute(
            select(
                Province.id,
                Nation.id,
                Nation.name,
                Nation.color_hex,
                Nation.short_name,
            )
            .join(Nation, Province.nation_id == Nation.id)
            .order_by(Province.id)
        )
        # Positional access: two `id` columns share a label name.
        return [
            OwnedProvinceInfo(
                province_id=row[0],
                nation_id=row[1],
                nation_name=row[2],
                nation_color=row[3],
                nation_short_name=row[4],
            )
            for row in result.all()
        ]


class PlayerService:
    """Service for Player entity operations."""

    @staticmethod
    async def get_or_create(session: AsyncSession, vk_user_id: int) -> Player:
        """
        Get an existing player by vk_user_id, or create a new one.

        Args:
            session: The async database session.
            vk_user_id: The VK user ID.

        Returns:
            The existing or newly created Player instance.
        """
        result = await session.execute(
            select(Player).where(Player.vk_user_id == vk_user_id)
        )
        player = result.scalar_one_or_none()

        if player is None:
            player = Player(
                id=str(uuid.uuid4()),
                vk_user_id=vk_user_id,
                created_at=datetime.now(UTC),
            )
            session.add(player)
            await session.flush()

        return player

    @staticmethod
    async def vk_user_ids(
        session: AsyncSession, player_ids: Iterable[str]
    ) -> dict[str, int]:
        """
        The ``player_id -> vk_user_id`` mapping for a set of players —
        the public read path for satellites that address VK users by
        their internal id (Spec 02_bot Part 1.3). Players absent from
        the table simply have no key in the result. Read-only, never
        commits.
        """
        ids = set(player_ids)
        if not ids:
            return {}
        result = await session.execute(
            select(Player.id, Player.vk_user_id).where(Player.id.in_(ids))
        )
        return {row[0]: row[1] for row in result.all()}

    @staticmethod
    async def list_for_registry(
        session: AsyncSession,
    ) -> list[PlayerRegistryRow]:
        """
        Every player joined to the nation they own (if any), ordered by
        (created_at, id) — the row-numbering order of Spec 03_registry
        3.2. Read-only and never commits.
        """
        result = await session.execute(
            select(
                Player.id,
                Player.vk_user_id,
                Player.created_at,
                Player.level,
                Player.judge_rating,
                Nation.id,
                Nation.name,
                Nation.color_hex,
                Nation.short_name,
                Nation.flag_id,
            )
            .outerjoin(Nation, Nation.owner_player_id == Player.id)
            .order_by(Player.created_at, Player.id)
        )
        return [
            PlayerRegistryRow(
                player_id=row[0],
                vk_user_id=row[1],
                created_at=row[2],
                level=row[3],
                judge_rating=row[4],
                nation_id=row[5],
                nation_name=row[6],
                nation_color=row[7],
                nation_short_name=row[8],
                nation_flag_id=row[9],
            )
            for row in result.all()
        ]

    @staticmethod
    async def count(session: AsyncSession) -> int:
        """
        ``SELECT count(*)`` on players — the public read path for
        satellites that need the total without the rows (Spec
        03_registry 5.4). Read-only and never commits.
        """
        result = await session.execute(select(func.count()).select_from(Player))
        return result.scalar_one()

    @staticmethod
    async def delete_player(session: AsyncSession, player_id: str) -> None:
        """
        Delete a player and everything tied to them (admin tool for
        test players — irreversible).

        Runs inside the caller's transaction, all-or-nothing; this
        method never commits. Order:

        1. ``NationService.delete`` for the player's nation, if any —
           it releases the provinces (INV-6), orphans scheduled actions
           and writes the release entries to the ownership journal
           through ``notify_ownership_changed`` in this transaction.
        2. Every registered ``player_delete`` hook, in registration
           order — each hook deletes only its own module's rows for
           this player (data sovereignty, invariant 3). There is NO
           per-hook savepoint: a raising hook aborts the deletion and
           the caller's rollback restores everything.
        3. The ``players`` row itself — a bulk DELETE, not ORM
           ``session.delete``: an ORM delete would lazy-load
           ``player.nations`` to null out FKs, which cannot happen in
           async context (and no nation remains anyway).

        Explicit hook deletes are what actually remove satellite rows —
        the FK ``ON DELETE CASCADE`` clauses are only a safety net for
        PostgreSQL; SQLite test schemas may run without enforced foreign
        keys.

        Raises:
            PlayerNotFoundError: If the player does not exist.
        """
        player = (
            await session.execute(select(Player).where(Player.id == player_id))
        ).scalar_one_or_none()
        if player is None:
            raise PlayerNotFoundError(player_id)

        nation = (
            await session.execute(
                select(Nation).where(Nation.owner_player_id == player_id)
            )
        ).scalar_one_or_none()
        if nation is not None:
            await NationService.delete(session, nation.id)

        for hook in get_player_delete_hooks().values():
            await hook(session, player_id)

        # Flush pending ORM deletes (the nation row) before the bulk
        # players DELETE: nations.owner_player_id carries a plain FK
        # without cascade, so the nation must be physically gone first.
        await session.flush()
        await session.execute(delete(Player).where(Player.id == player_id))


async def _current_turn(session: AsyncSession) -> int:
    """
    The game_clock.current_turn of the running transaction.

    A migrated database always holds the singleton row (migration 0001);
    bare create_all test schemas may not — in that case the change is
    stamped turn 0 rather than failing the operation.
    """
    result = await session.execute(select(GameClock).where(GameClock.id == 1))
    clock = result.scalar_one_or_none()
    return clock.current_turn if clock is not None else 0


class GameClockService:
    """Read-only access to the game_clock singleton for satellites."""

    @staticmethod
    async def current_turn(session: AsyncSession) -> int:
        """
        The current turn in the caller's transaction. Shares the
        write path's rule: a missing singleton row (bare test schema)
        reads as turn 0.
        """
        return await _current_turn(session)

    @staticmethod
    async def snapshot(session: AsyncSession) -> GameClockSnapshot | None:
        """
        The whole ``game_clock`` row as a detached snapshot — the
        public read path for satellites that need ``last_tick_at`` /
        ``next_tick_at`` (Spec 02_bot Part 1.3). Returns None when the
        singleton row is absent (unmigrated schema). Never commits.
        """
        result = await session.execute(select(GameClock).where(GameClock.id == 1))
        clock = result.scalar_one_or_none()
        if clock is None:
            return None
        return GameClockSnapshot(
            current_turn=clock.current_turn,
            last_tick_at=clock.last_tick_at,
            next_tick_at=clock.next_tick_at,
        )


async def _take_nations_lock(session: AsyncSession) -> None:
    """
    The nations advisory lock (INV-13): serializes the name/short-name/
    color check-then-write sequence across processes on PostgreSQL —
    two concurrent registrations with similar colors cannot both pass.
    Held until the transaction ends; the service never commits. SQLite
    skips it: the single writer needs no lock.
    """
    if session.bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": NATIONS_ADVISORY_LOCK_KEY},
        )


async def _evaluate_color(
    session: AsyncSession,
    color_hex: str,
    config: CoreConfig,
    exclude_nation_id: str | None = None,
) -> ColorStatus:
    """
    The Part 3 color decision (INV-13), on an uppercase input: exact
    match against another nation's color -> TAKEN; distance below
    ``min_distance_reserved`` to a map color -> TOO_CLOSE; distance
    below ``min_distance_nations`` to another nation's color ->
    TOO_CLOSE; otherwise OK. Threshold equality passes (strict less).
    ``exclude_nation_id`` drops one nation from both comparisons.
    """
    stmt = select(Nation.color_hex)
    if exclude_nation_id is not None:
        stmt = stmt.where(Nation.id != exclude_nation_id)
    result = await session.execute(stmt)
    taken = result.scalars().all()

    for existing in taken:
        if existing.upper() == color_hex:
            return "TAKEN"
    for reserved in config.color.reserved:
        if oklab_distance(color_hex, reserved.hex) < config.color.min_distance_reserved:
            return "TOO_CLOSE"
    for existing in taken:
        if oklab_distance(color_hex, existing) < config.color.min_distance_nations:
            return "TOO_CLOSE"
    return "OK"


async def _check_color_or_raise(
    session: AsyncSession,
    color_hex: str,
    config: CoreConfig,
    exclude_nation_id: str | None = None,
) -> None:
    """Raise the domain error matching the color decision."""
    status = await _evaluate_color(session, color_hex, config, exclude_nation_id)
    if status == "TAKEN":
        raise ColorTakenError(color_hex)
    if status == "TOO_CLOSE":
        raise ColorTooCloseError(color_hex)


class NationService:
    """Service for Nation entity operations."""

    @staticmethod
    async def create(
        session: AsyncSession,
        owner_player_id: str,
        name: str,
        color_hex: str,
        province_ids: list[int],
        config: CoreConfig,
        leader_name: str,
        leader_title: str,
        history_url: str,
        short_name: str,
        gender: str,
        succession_type: str,
        capital_name: str,
        capital_province_id: int | None = None,
        motto: str | None = None,
        description: str | None = None,
        leader_bio: str | None = None,
        flag_id: str | None = None,
        portrait_id: str | None = None,
        anthem_url: str | None = None,
    ) -> Nation:
        """
        Create a new nation with the given provinces and profile fields.

        The Spec Part 2 check order (extended by 01_map Part 5 and
        02_bot 3.10/3.11): "before_all" satellite checks (they see the
        player, run before any write) -> INV-1 -> descriptive fields in
        the fixed order (leader_name, leader_title, gender,
        succession_type, history_url, anthem_url, short_name, motto,
        description, leader_bio, flag_id, portrait_id, capital_name —
        the first violation wins) -> the nations lock -> INV-2 for the
        name -> INV-11 for the short name -> the color decision
        (COLOR_TAKEN / COLOR_TOO_CLOSE) -> province existence ->
        province freedom -> "after_free" checks -> province count ->
        "after_count" checks -> capital membership
        (CAPITAL_NOT_IN_PROVINCES) -> creation, the ownership
        notification and the "nation_created" hooks (after all writes,
        each under its own SAVEPOINT). Any check failure persists
        nothing (INV-3).

        Args:
            session: The async database session.
            owner_player_id: The player ID who will own the nation.
            name: The nation name (normalized by strip).
            color_hex: The nation color in hex format (#RRGGBB).
            province_ids: List of province IDs to assign to the nation.
            config: The core configuration for validation constraints.
            leader_name: The leader's name (normalized and validated).
            leader_title: The leader's title (normalized and validated).
            history_url: Link to the nation's history article.
            short_name: The nation's short name (unique, INV-11).
            gender: The leader's gender (code constant).
            succession_type: How the next leader takes over (code).
            capital_name: The capital's name.
            capital_province_id: The capital province; defaults to the
                first element of ``province_ids`` as sent (INV-14).
            motto: Optional motto; empty after normalization -> NULL.
            description: Optional description; empty -> NULL.
            leader_bio: Optional multi-line leader bio; empty -> NULL.
            flag_id: Mandatory catalog flag id since 0.9.0 (INV-15).
            portrait_id: Mandatory catalog portrait id since 0.9.0.
            anthem_url: Optional anthem link (soft check, Part 3);
                unused since 0.9.0, removal is on the 00_core backlog.

        Returns:
            The newly created Nation instance.

        Raises:
            NationAlreadyExistsError: If the player already has a nation.
            NameTakenError: If the name is already taken.
            ShortNameTakenError: If the short name is already taken.
            ColorTakenError: If the color exactly matches a nation's.
            ColorTooCloseError: If the color is too close to a nation
                or a reserved map color.
            ProvinceNotFoundError: If any province ID does not exist.
            ProvinceTakenError: If any province is already owned.
            ProvinceCountOutOfRangeError: If province count violates constraints.
            CapitalNotInProvincesError: If the capital is not selected.
            The ``*_INVALID`` errors of Part 5 for failed field checks.
        """
        # Stage "before_all": satellite checks that see the player and
        # run before any write — first in the Spec Part 5 order.
        await run_before_all_checks(session, owner_player_id)

        # INV-1: Check if player already has a nation
        result = await session.execute(
            select(Nation).where(Nation.owner_player_id == owner_player_id)
        )
        if result.scalar_one_or_none() is not None:
            raise NationAlreadyExistsError(owner_player_id)

        # Descriptive fields, validated in the Spec Part 2 fixed order;
        # the normalized values get stored (INV-7, INV-12).
        leader_name = validate_leader_name(leader_name, config)
        leader_title = validate_leader_title(leader_title, config)
        gender = validate_gender(gender, config)
        succession_type = validate_succession_type(succession_type, config)
        history_url = validate_history_url(history_url, config)
        anthem_url = validate_anthem_url(anthem_url, config)
        short_name = validate_short_name(short_name, config)
        motto = validate_motto(motto, config)
        description = validate_description(description, config)
        leader_bio = validate_leader_bio(leader_bio, config)
        flag_id = validate_flag_id(flag_id, config)
        # Since 0.9.0 a new nation always has a flag and a portrait
        # (20.10.2026); NULL is rejected only on create — legacy rows
        # from before 0.9.0 keep their NULLs through PATCH.
        if flag_id is None:
            raise FlagInvalidError("a flag from the catalog is required")
        portrait_id = validate_portrait_id(portrait_id, config)
        if portrait_id is None:
            raise PortraitInvalidError("a leader portrait from the catalog is required")
        capital_name = validate_capital_name(capital_name, config)

        # The lock covers name/short-name/color reads so concurrent
        # registrations cannot interleave check and insert (INV-13).
        await _take_nations_lock(session)

        # INV-2: Check if name is already taken (normalized by strip).
        name = name.strip()
        result = await session.execute(select(Nation).where(Nation.name == name))
        if result.scalar_one_or_none() is not None:
            raise NameTakenError(name)

        # INV-11: Check if the short name is already taken.
        result = await session.execute(
            select(Nation).where(Nation.short_name == short_name)
        )
        if result.scalar_one_or_none() is not None:
            raise ShortNameTakenError(short_name)

        # INV-13: uppercase normalization before every color check.
        color_hex = color_hex.upper()
        await _check_color_or_raise(session, color_hex, config)

        # Fetch all provinces to validate they exist and are free
        result = await session.execute(
            select(Province).where(Province.id.in_(province_ids))
        )
        provinces = result.scalars().all()

        # Check for missing provinces
        found_ids = {p.id for p in provinces}
        missing_ids = set(province_ids) - found_ids
        if missing_ids:
            raise ProvinceNotFoundError(missing_ids.pop())

        # Check for already-owned provinces
        for province in provinces:
            if province.nation_id is not None:
                raise ProvinceTakenError(province.id)

        # Stage "after_free": satellite checks that need a loaded,
        # existing, free province set (Spec 01_map Part 5 order).
        await run_registration_checks(STAGE_AFTER_FREE, session, provinces)

        # Validate province count constraints
        province_count = len(province_ids)
        if (
            province_count < config.nation.min_provinces_per_nation
            or province_count > config.nation.max_provinces_per_nation
        ):
            raise ProvinceCountOutOfRangeError(
                province_count,
                config.nation.min_provinces_per_nation,
                config.nation.max_provinces_per_nation,
            )

        # Stage "after_count": satellite checks on the sized group.
        await run_registration_checks(STAGE_AFTER_COUNT, session, provinces)

        # INV-14: the capital must be one of the selected provinces;
        # absent means the first element of province_ids as sent.
        if capital_province_id is None:
            capital_province_id = province_ids[0]
        if capital_province_id not in province_ids:
            raise CapitalNotInProvincesError(capital_province_id)

        # INV-3: Atomic transaction - create nation and assign provinces.
        # created_turn stamps the transaction's current turn (Spec
        # 03_registry 1.4; INV-R9: never changed afterwards).
        turn = await _current_turn(session)
        nation = Nation(
            id=str(uuid.uuid4()),
            owner_player_id=owner_player_id,
            name=name,
            color_hex=color_hex,
            leader_name=leader_name,
            leader_title=leader_title,
            history_url=history_url,
            short_name=short_name,
            gender=gender,
            succession_type=succession_type,
            motto=motto,
            description=description,
            leader_bio=leader_bio,
            flag_id=flag_id,
            portrait_id=portrait_id,
            anthem_url=anthem_url,
            capital_province_id=capital_province_id,
            capital_name=capital_name,
            created_at=datetime.now(UTC),
            created_turn=turn,
        )
        session.add(nation)
        await session.flush()  # Get the nation ID

        # Assign provinces — the ONLY production code path that writes
        # provinces.nation_id outside the admin world reset. Every such
        # write is announced through notify_ownership_changed in the same
        # transaction (INV-M7).
        ordered = sorted(provinces, key=lambda p: p.id)
        for province in ordered:
            province.nation_id = nation.id
        await notify_ownership_changed(
            session,
            [
                OwnershipChange(
                    province_id=province.id,
                    prev_nation_id=None,
                    new_nation_id=nation.id,
                    new_name=nation.name,
                    new_short_name=nation.short_name,
                    new_color=nation.color_hex,
                    turn=turn,
                )
                for province in ordered
            ],
        )

        # Spec 02_bot 3.11 / Appendix B10: "nation created" satellite
        # hooks run after all creation writes, still inside the caller's
        # transaction — each under its own SAVEPOINT so a failing hook
        # keeps neither its writes nor blocks the registration.
        await run_nation_created_hooks(session, owner_player_id, nation.id)

        return nation

    @staticmethod
    async def player_nation_summary(
        session: AsyncSession, player_id: str
    ) -> PlayerNationSummary | None:
        """
        The nation owned by ``player_id`` with its display fields and
        live province count — the public read path for satellites
        (Spec 02_bot Part 1.3; also serves the "has nation" check).
        Returns None when the player owns no nation. Read-only, never
        commits.
        """
        result = await session.execute(
            select(Nation).where(Nation.owner_player_id == player_id)
        )
        nation = result.scalar_one_or_none()
        if nation is None:
            return None
        count_result = await session.execute(
            select(func.count())
            .select_from(Province)
            .where(Province.nation_id == nation.id)
        )
        return PlayerNationSummary(
            nation_id=nation.id,
            name=nation.name,
            leader_name=nation.leader_name,
            leader_title=nation.leader_title,
            province_count=count_result.scalar_one(),
            color_hex=nation.color_hex,
            short_name=nation.short_name,
            flag_id=nation.flag_id,
        )

    @staticmethod
    async def existing_ids(
        session: AsyncSession, nation_ids: Iterable[str]
    ) -> set[str]:
        """
        The subset of ``nation_ids`` still present in the nations table —
        one batched read for satellites (e.g. /map/state resolving which
        past owners still exist). Read-only and never commits.
        """
        ids = set(nation_ids)
        if not ids:
            return set()
        result = await session.execute(select(Nation.id).where(Nation.id.in_(ids)))
        return set(result.scalars().all())

    @staticmethod
    async def list_for_registry(
        session: AsyncSession,
    ) -> list[NationRegistryRow]:
        """
        Every nation with its live province count, ordered by
        (created_turn, created_at, id) — the row-numbering order of
        Spec 03_registry 3.3. The count is a correlated subquery over
        provinces.nation_id; sea zones can never be owned
        (ck_provinces_sea_unowned), so they need no special case.
        Read-only and never commits.
        """
        province_count = (
            select(func.count())
            .select_from(Province)
            .where(Province.nation_id == Nation.id)
            .scalar_subquery()
        )
        result = await session.execute(
            select(
                Nation.id,
                Nation.name,
                Nation.color_hex,
                Nation.created_turn,
                Nation.created_at,
                province_count,
                Nation.short_name,
                Nation.flag_id,
            ).order_by(Nation.created_turn, Nation.created_at, Nation.id)
        )
        return [
            NationRegistryRow(
                nation_id=row[0],
                name=row[1],
                color_hex=row[2],
                created_turn=row[3],
                created_at=row[4],
                province_count=row[5],
                short_name=row[6],
                flag_id=row[7],
            )
            for row in result.all()
        ]

    @staticmethod
    async def count(session: AsyncSession) -> int:
        """
        ``SELECT count(*)`` on nations — the public read path for
        satellites that need the total without the rows (Spec
        03_registry 5.4). Read-only and never commits.
        """
        result = await session.execute(select(func.count()).select_from(Nation))
        return result.scalar_one()

    @staticmethod
    async def update(
        session: AsyncSession,
        nation_id: str,
        name: str | None = None,
        color_hex: str | None = None,
        leader_name: str | None = None,
        leader_title: str | None = None,
        history_url: str | None = None,
        short_name: str | None = None,
        gender: str | None = None,
        succession_type: str | None = None,
        motto: str | None = None,
        description: str | None = None,
        leader_bio: str | None = None,
        flag_id: str | None = None,
        portrait_id: str | None = None,
        anthem_url: str | None = None,
        capital_name: str | None = None,
        *,
        config: CoreConfig,
    ) -> Nation:
        """
        Update a nation's descriptive fields (PATCH semantics, INV-8).

        None/absent means "do not change". A provided value is
        normalized and validated up front — a rejected field aborts the
        whole update before anything is mutated. Mandatory fields can
        never be cleared: an empty (post-strip) value is a validation
        error, not a reset. Optional fields (motto, description,
        leader_bio, flag_id, portrait_id, anthem_url) are cleared to
        NULL by an empty value. Provinces and the capital province are
        not changeable here (INV-14); ``capital_name`` may only be set
        on a nation that has a capital — a pre-0.8.0 nation without one
        can never gain it through editing. Legacy nations with NULL
        mandatory fields still accept unrelated-field edits.

        Check order (Spec Part 2): provided descriptive fields in the
        create order -> the nations lock -> name uniqueness -> short
        name uniqueness -> the color decision (only when the color
        changes; the nation itself is excluded) -> write.

        Raises:
            NationNotFoundError: If the nation does not exist.
            NameTakenError: If the new name is already taken.
            ShortNameTakenError: If the new short name is already taken.
            ColorTakenError: If the new color exactly matches a nation's.
            ColorTooCloseError: If the new color is too close to a
                nation or a reserved map color.
            CapitalNotInProvincesError: If capital_name targets a
                nation without a capital province.
            The ``*_INVALID`` errors of Part 5 for failed field checks.
        """
        result = await session.execute(select(Nation).where(Nation.id == nation_id))
        nation = result.scalar_one_or_none()

        if nation is None:
            raise NationNotFoundError(nation_id)

        # INV-8: validate every provided field before any mutation, in
        # the Spec Part 2 field order — a bad field leaves the whole
        # update untouched.
        new_leader_name = (
            None if leader_name is None else validate_leader_name(leader_name, config)
        )
        new_leader_title = (
            None
            if leader_title is None
            else validate_leader_title(leader_title, config)
        )
        new_gender = None if gender is None else validate_gender(gender, config)
        new_succession_type = (
            None
            if succession_type is None
            else validate_succession_type(succession_type, config)
        )
        new_history_url = (
            None if history_url is None else validate_history_url(history_url, config)
        )
        new_anthem_url = validate_anthem_url(anthem_url, config)
        new_short_name = (
            None if short_name is None else validate_short_name(short_name, config)
        )
        new_motto = validate_motto(motto, config)
        new_description = validate_description(description, config)
        new_leader_bio = validate_leader_bio(leader_bio, config)
        new_flag_id = validate_flag_id(flag_id, config)
        new_portrait_id = validate_portrait_id(portrait_id, config)
        new_capital_name = (
            None
            if capital_name is None
            else validate_capital_name(capital_name, config)
        )

        # The lock covers the name/short-name/color reads and the
        # subsequent write on PostgreSQL (INV-13).
        await _take_nations_lock(session)

        if name is not None:
            new_name = name.strip()
            if new_name != nation.name:
                result = await session.execute(
                    select(Nation).where(
                        Nation.name == new_name, Nation.id != nation_id
                    )
                )
                if result.scalar_one_or_none() is not None:
                    raise NameTakenError(new_name)
            nation.name = new_name

        if new_short_name is not None and new_short_name != nation.short_name:
            result = await session.execute(
                select(Nation).where(
                    Nation.short_name == new_short_name,
                    Nation.id != nation_id,
                )
            )
            if result.scalar_one_or_none() is not None:
                raise ShortNameTakenError(new_short_name)

        if color_hex is not None:
            new_color = color_hex.upper()
            if new_color != nation.color_hex:
                await _check_color_or_raise(
                    session, new_color, config, exclude_nation_id=nation_id
                )
                nation.color_hex = new_color

        if new_capital_name is not None:
            if nation.capital_province_id is None:
                # A pre-0.8.0 nation has no capital and cannot gain one
                # through editing (INV-14).
                raise CapitalNotInProvincesError(nation.capital_province_id)
            nation.capital_name = new_capital_name

        if new_leader_name is not None:
            nation.leader_name = new_leader_name
        if new_leader_title is not None:
            nation.leader_title = new_leader_title
        if new_history_url is not None:
            nation.history_url = new_history_url
        if anthem_url is not None:
            nation.anthem_url = new_anthem_url
        if new_short_name is not None:
            nation.short_name = new_short_name
        if new_gender is not None:
            nation.gender = new_gender
        if new_succession_type is not None:
            nation.succession_type = new_succession_type
        if motto is not None:
            nation.motto = new_motto
        if description is not None:
            nation.description = new_description
        if leader_bio is not None:
            nation.leader_bio = new_leader_bio
        if flag_id is not None:
            nation.flag_id = new_flag_id
        if portrait_id is not None:
            nation.portrait_id = new_portrait_id

        return nation

    @staticmethod
    async def color_status(
        session: AsyncSession,
        color_hex: str,
        config: CoreConfig,
        exclude_nation_id: str | None = None,
    ) -> ColorStatus:
        """
        The Part 3 color decision for the color-check endpoint: the
        same functions as the write path, but WITHOUT the lock and
        without any write — an "OK" answer does not guarantee a later
        creation succeeds (the final decision happens inside
        ``create`` under the advisory lock). ``exclude_nation_id``
        removes the caller's own nation from the comparison.
        Read-only and never commits.
        """
        return await _evaluate_color(
            session, color_hex.upper(), config, exclude_nation_id
        )

    @staticmethod
    async def delete(session: AsyncSession, nation_id: str) -> None:
        """
        Delete a nation and free its provinces.

        Enforces INV-6: deletion frees provinces instead of deleting them.

        Args:
            session: The async database session.
            nation_id: The nation ID to delete.

        Raises:
            NationNotFoundError: If the nation does not exist.
        """
        result = await session.execute(select(Nation).where(Nation.id == nation_id))
        nation = result.scalar_one_or_none()

        if nation is None:
            raise NationNotFoundError(nation_id)

        # INV-6: Free all provinces by setting nation_id to NULL
        # Use select to fetch provinces to avoid lazy loading in async context
        result = await session.execute(
            select(Province).where(Province.nation_id == nation_id)
        )
        provinces = result.scalars().all()
        for province in provinces:
            province.nation_id = None

        # Orphan scheduled actions the same way: explicit nulling, not
        # FK cascade, so SQLite (foreign_keys pragma off) behaves
        # identically to PostgreSQL ON DELETE SET NULL.
        result = await session.execute(
            select(ScheduledAction).where(ScheduledAction.nation_id == nation_id)
        )
        for action in result.scalars().all():
            action.nation_id = None

        # Delete the nation
        await session.delete(nation)

        # Announce the releases inside the same transaction (INV-M7):
        # listeners keep the deleted nation's identity (id) per change.
        turn = await _current_turn(session)
        await notify_ownership_changed(
            session,
            [
                OwnershipChange(
                    province_id=province.id,
                    prev_nation_id=nation_id,
                    new_nation_id=None,
                    new_name=None,
                    new_short_name=None,
                    new_color=None,
                    turn=turn,
                )
                for province in sorted(provinces, key=lambda p: p.id)
            ],
        )


class ScheduledActionService:
    """Service for ScheduledAction entity operations."""

    @staticmethod
    async def submit(
        session: AsyncSession,
        nation_id: str,
        module_slug: str,
        action_type: str,
        payload: dict,
        turn_number: int,
        frequency_rule: str,
        frequency_cap: int | None = None,
    ) -> ScheduledAction:
        """
        Submit a scheduled action for execution.

        Enforces INV-FREQUENCY: validates action frequency based on the rule.

        Args:
            session: The async database session.
            nation_id: The nation ID submitting the action.
            module_slug: The module that owns this action.
            action_type: The type of action within the module.
            payload: The action payload (interpreted by the module).
            turn_number: The turn number this action is scheduled for.
            frequency_rule: The frequency rule (see FrequencyRule).
            frequency_cap: The cap for MULTIPLE_PER_TURN rule.

        Returns:
            The newly created ScheduledAction instance.

        Raises:
            FrequencyCapExceededError: If the frequency cap is exceeded.
        """
        # INV-FREQUENCY: Check frequency constraints
        max_allowed = None

        conditions = [
            ScheduledAction.nation_id == nation_id,
            ScheduledAction.module_slug == module_slug,
            ScheduledAction.action_type == action_type,
            ScheduledAction.status == ScheduledActionStatus.PENDING,
        ]
        if frequency_rule in (
            FrequencyRule.ONCE_PER_TURN,
            FrequencyRule.MULTIPLE_PER_TURN,
        ):
            conditions.append(ScheduledAction.turn_number == turn_number)

        # Count actions for this nation, module, type, on this specific turn
        result = await session.execute(select(ScheduledAction).where(*conditions))
        current_count = len(result.scalars().all())

        if frequency_rule == FrequencyRule.ONCE_PER_TURN:
            max_allowed = 1
        elif frequency_rule == FrequencyRule.ONCE_PER_GAME:
            max_allowed = 1
        elif frequency_rule == FrequencyRule.MULTIPLE_PER_TURN:
            if frequency_cap is None:
                raise ValueError("frequency_cap is required for MULTIPLE_PER_TURN rule")
            max_allowed = frequency_cap
        elif frequency_rule == FrequencyRule.UNLIMITED:
            max_allowed = float("inf")
        else:
            raise ValueError(f"Unknown frequency rule: {frequency_rule}")

        # Check if cap is exceeded
        if current_count >= max_allowed:
            raise FrequencyCapExceededError(action_type, current_count, max_allowed)

        # Create the scheduled action
        action = ScheduledAction(
            id=str(uuid.uuid4()),
            nation_id=nation_id,
            module_slug=module_slug,
            action_type=action_type,
            payload=payload,
            turn_number=turn_number,
            status=ScheduledActionStatus.PENDING,
            created_at=datetime.now(UTC),
        )
        session.add(action)
        await session.flush()

        return action
