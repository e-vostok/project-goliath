"""
Registration 2.0 tests (Spec 1.3, Issue 10).

Covers what the pre-1.3 suites could not say:

- the OKLab conversion/distance test vectors of Part 3 (tolerance 1e-5);
- every new Part 5 error code on the create path;
- the Part 2 check order that only Registration 2.0 makes observable
  (short-name uniqueness before the color decision, the color decision
  before province existence, capital membership after the count);
- PATCH semantics for the new fields (mandatory empty -> error,
  optional empty -> NULL, absent -> keep, own color excluded);
- the color-check endpoint's three statuses and self-exclusion;
- migration 0011 up/down on a real SQLite file: new columns appear
  NULLABLE, the named UNIQUE and capital FK exist, existing rows are
  untouched, downgrade removes exactly the eleven columns.

The concurrent-registration color race lives in
``test_registration_2_pg.py`` (needs real PostgreSQL).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from alembic import command
from core.db import get_session
from main import app
from modules._00_core.color_policy import hex_to_oklab, oklab_distance
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import (
    AnthemUrlInvalidError,
    CapitalNameInvalidError,
    CapitalNotInProvincesError,
    ColorTakenError,
    ColorTooCloseError,
    DescriptionInvalidError,
    FlagInvalidError,
    GenderInvalidError,
    LeaderBioInvalidError,
    LeaderNameInvalidError,
    MottoInvalidError,
    NameTakenError,
    PortraitInvalidError,
    ProvinceCountOutOfRangeError,
    ShortNameInvalidError,
    ShortNameTakenError,
    SuccessionInvalidError,
)
from modules._00_core.models import Nation, Player
from modules._00_core.service import NationService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import make_land_province
from tests.modules._00_core.test_router import (
    TEST_JWT_SECRET,
    TEST_VK_SECRET,
    bearer_headers,
    seed_nation,
    seed_player,
    seed_provinces,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

STARTING = [1001, 1002, 1003, 1004, 1005]
STARTING_2 = [1006, 1007, 1008, 1009, 1010]
# Palette colors — guaranteed far enough from every reserved map color.
COLOR_A = "#0C7CF4"
COLOR_B = "#6A3446"
COLOR_C = "#058D1D"


@pytest.fixture(autouse=True)
def env_secrets(monkeypatch):
    """Provide VK/JWT secrets for every test."""
    monkeypatch.setenv("VK_APP_SECRET", TEST_VK_SECRET)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)


@pytest.fixture
def config() -> CoreConfig:
    return CORE_CONFIG


@pytest_asyncio.fixture
async def client(test_db_session):
    """HTTP client bound to the real app, backed by the test session
    (the same wiring every core API test uses)."""

    async def _override_get_session():
        yield test_db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _player(session, vk_user_id: int = 510001) -> Player:
    player = Player(vk_user_id=vk_user_id)
    session.add(player)
    await session.flush()
    return player


async def _land(session, ids: list[int]) -> None:
    for pid in ids:
        await make_land_province(session, id=pid)


async def _create(session, player: Player, config: CoreConfig, **overrides) -> Nation:
    kwargs = {
        "owner_player_id": player.id,
        "name": "Testland Realm",
        "color_hex": COLOR_A,
        "province_ids": STARTING,
        **VALID_PROFILE,
        **overrides,
    }
    return await NationService.create(session, config=config, **kwargs)


class TestOklabVectors:
    """The Part 3 vectors, tolerance 1e-5 per component."""

    @pytest.mark.parametrize(
        "hex_color,expected",
        [
            ("#000000", (0.0, 0.0, 0.0)),
            ("#FFFFFF", (1.0, 0.0, 0.0)),
            ("#8C8C8C", (0.640087, 0.0, 0.0)),
            ("#FF0000", (0.627955, 0.224863, 0.125846)),
            ("#00FF00", (0.866440, -0.233888, 0.179498)),
            ("#141E26", (0.229243, -0.009648, -0.018895)),
        ],
    )
    def test_hex_to_oklab(self, hex_color, expected):
        lab = hex_to_oklab(hex_color)
        for got, want in zip(lab, expected, strict=True):
            assert got == pytest.approx(want, abs=1e-5)

    @pytest.mark.parametrize(
        "first,second,expected",
        [
            ("#000000", "#FFFFFF", 1.000000),
            ("#FF0000", "#00FF00", 0.519813),
            ("#0C7CF4", "#2B2DB0", 0.207907),
            # Below every config threshold — always a refusal.
            ("#8C8C8C", "#8F8F8F", 0.009954),
            ("#BE1253", "#C01355", 0.005012),
            # Below the 0.08 thresholds — a refusal too.
            ("#8C8C8C", "#9A9A9A", 0.046136),
            ("#8C8C8C", "#A0A0A0", 0.065670),
            # Case does not matter.
            ("#ff0000", "#FF0000", 0.0),
        ],
    )
    def test_oklab_distance(self, first, second, expected):
        assert oklab_distance(first, second) == pytest.approx(expected, abs=1e-5)


class TestFieldErrorCodes:
    """Every new ``*_INVALID`` code of Part 5 on the create path."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "field,value,error",
        [
            ("leader_name", "x", LeaderNameInvalidError),
            ("gender", "robot", GenderInvalidError),
            ("gender", "", GenderInvalidError),
            ("succession_type", "monarchy", SuccessionInvalidError),
            ("anthem_url", "http://vk.com/audio-1", AnthemUrlInvalidError),
            (
                "anthem_url",
                "https://evil.com/audio-1",
                AnthemUrlInvalidError,
            ),
            ("short_name", "x", ShortNameInvalidError),
            ("short_name", "", ShortNameInvalidError),
            ("motto", "m" * 61, MottoInvalidError),
            ("motto", "line\nbreak", MottoInvalidError),
            ("description", "d" * 101, DescriptionInvalidError),
            ("leader_bio", "b" * 501, LeaderBioInvalidError),
            ("leader_bio", "tab\there", LeaderBioInvalidError),
            ("flag_id", "nope", FlagInvalidError),
            ("portrait_id", "nope", PortraitInvalidError),
            ("capital_name", "", CapitalNameInvalidError),
            ("capital_name", "c" * 41, CapitalNameInvalidError),
        ],
    )
    async def test_invalid_field_maps_to_code(
        self, test_db_session, config, field, value, error
    ):
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)

        with pytest.raises(error):
            await _create(test_db_session, player, config, **{field: value})

    @pytest.mark.asyncio
    async def test_short_name_taken(self, test_db_session, config):
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING + STARTING_2)
        await _create(test_db_session, player_a, config)

        with pytest.raises(ShortNameTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Second Realm",
                color_hex=COLOR_B,
                province_ids=STARTING_2,
            )

    @pytest.mark.asyncio
    async def test_color_too_close_to_reserved(self, test_db_session, config):
        """A color under min_distance_reserved of a map color refuses."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)

        with pytest.raises(ColorTooCloseError):
            await _create(test_db_session, player, config, color_hex="#8F8F8F")

    @pytest.mark.asyncio
    async def test_color_too_close_to_nation(self, test_db_session, config):
        """A color under min_distance_nations of another nation refuses;
        the nearly identical #0C7DF5 sits ~0.006 from COLOR_A."""
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING + STARTING_2)
        await _create(test_db_session, player_a, config)

        with pytest.raises(ColorTooCloseError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Second Realm",
                short_name="Second",
                color_hex="#0C7DF5",
                province_ids=STARTING_2,
            )

    @pytest.mark.asyncio
    async def test_capital_not_in_provinces(self, test_db_session, config):
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)

        with pytest.raises(CapitalNotInProvincesError):
            await _create(
                test_db_session,
                player,
                config,
                capital_province_id=1999,
            )


class TestCheckOrder:
    """The Part 2 order lines that Registration 2.0 makes observable."""

    @pytest.mark.asyncio
    async def test_name_taken_before_short_name_taken(self, test_db_session, config):
        """INV-2 for the name precedes INV-11: a request that violates
        both answers NAME_TAKEN."""
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING + STARTING_2)
        await _create(test_db_session, player_a, config)

        with pytest.raises(NameTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                short_name="Whatever",
                color_hex=COLOR_B,
                province_ids=STARTING_2,
            )

    @pytest.mark.asyncio
    async def test_short_name_taken_before_color(self, test_db_session, config):
        """INV-11 precedes the color decision: a taken short name plus
        a taken color answers SHORT_NAME_TAKEN."""
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING + STARTING_2)
        await _create(test_db_session, player_a, config)

        with pytest.raises(ShortNameTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Second Realm",
                # same short_name AND same color — the earlier check wins
                color_hex=COLOR_A,
                province_ids=STARTING_2,
            )

    @pytest.mark.asyncio
    async def test_color_before_province_existence(self, test_db_session, config):
        """The color decision precedes the province reads: a taken
        color with nonexistent provinces answers COLOR_TAKEN."""
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING)
        await _create(test_db_session, player_a, config)

        with pytest.raises(ColorTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Second Realm",
                short_name="Second",
                color_hex=COLOR_A.lower(),  # normalized to upper first
                province_ids=[9001, 9002, 9003, 9004, 9005],
            )

    @pytest.mark.asyncio
    async def test_count_before_capital_membership(self, test_db_session, config):
        """The province count precedes the capital check (INV-14 is
        verified after ``after_count``): four provinces plus a bad
        capital answers PROVINCE_COUNT_OUT_OF_RANGE."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING[:4])

        with pytest.raises(ProvinceCountOutOfRangeError):
            await _create(
                test_db_session,
                player,
                config,
                province_ids=STARTING[:4],
                capital_province_id=1999,
            )

    @pytest.mark.asyncio
    async def test_field_order_gender_before_short_name(self, test_db_session, config):
        """Field checks run in the Part 2 fixed order — gender precedes
        short_name, so the gender error wins when both are bad."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)

        with pytest.raises(GenderInvalidError):
            await _create(
                test_db_session,
                player,
                config,
                gender="robot",
                short_name="x",
            )


class TestUpdateSemantics:
    """PATCH semantics for the new fields (INV-8/INV-12/INV-14)."""

    @pytest.mark.asyncio
    async def test_optional_fields_clear_to_null(self, test_db_session, config):
        """An empty (post-strip) value clears an optional field to NULL;
        absent keeps the previous value."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)
        nation = await _create(
            test_db_session,
            player,
            config,
            motto="Glory to Testland",
            description="A test nation",
            leader_bio="Line one\nLine two",
            anthem_url="https://vk.com/audio-2001_1",
        )

        nation = await NationService.update(
            test_db_session,
            nation.id,
            motto="",
            leader_bio="   ",
            config=config,
        )

        assert nation.motto is None
        assert nation.leader_bio is None
        # Untouched optionals keep their values.
        assert nation.description == "A test nation"
        assert nation.anthem_url == "https://vk.com/audio-2001_1"

    @pytest.mark.asyncio
    async def test_mandatory_empty_is_error_not_clear(self, test_db_session, config):
        """INV-8: an empty mandatory field is a validation error."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)
        nation = await _create(test_db_session, player, config)

        for field, error in [
            ("short_name", ShortNameInvalidError),
            ("gender", GenderInvalidError),
            ("succession_type", SuccessionInvalidError),
            ("capital_name", CapitalNameInvalidError),
            ("leader_name", LeaderNameInvalidError),
        ]:
            with pytest.raises(error):
                await NationService.update(
                    test_db_session,
                    nation.id,
                    **{field: ""},
                    config=config,
                )
        # Nothing changed — every attempt aborted before the write.
        await test_db_session.refresh(nation)
        assert nation.short_name == VALID_PROFILE["short_name"]
        assert nation.gender == "male"

    @pytest.mark.asyncio
    async def test_own_color_excluded_on_update(self, test_db_session, config):
        """Re-submitting the unchanged color is fine; a new color too
        close to another nation is refused; the nation's own color is
        excluded from the comparison."""
        player_a = await _player(test_db_session, 510002)
        player_b = await _player(test_db_session, 510003)
        await _land(test_db_session, STARTING + STARTING_2)
        nation_a = await _create(test_db_session, player_a, config)
        await _create(
            test_db_session,
            player_b,
            config,
            name="Second Realm",
            short_name="Second",
            color_hex=COLOR_B,
            province_ids=STARTING_2,
        )

        # Same color (even lower-cased) — the change is a no-op.
        nation_a = await NationService.update(
            test_db_session,
            nation_a.id,
            color_hex="#0c7cf4",
            config=config,
        )
        assert nation_a.color_hex == COLOR_A

        with pytest.raises(ColorTakenError):
            await NationService.update(
                test_db_session,
                nation_a.id,
                color_hex=COLOR_B,
                config=config,
            )
        with pytest.raises(ColorTooCloseError):
            await NationService.update(
                test_db_session,
                nation_a.id,
                color_hex="#6B3547",  # ~0.006 from COLOR_B
                config=config,
            )
        with pytest.raises(ColorTooCloseError):
            await NationService.update(
                test_db_session,
                nation_a.id,
                color_hex="#9A9A9A",  # 0.046 from reserved #8C8C8C
                config=config,
            )

    @pytest.mark.asyncio
    async def test_capital_name_requires_a_capital(self, test_db_session, config):
        """INV-14: a pre-0.8.0 nation without a capital province cannot
        gain a capital name through editing."""
        player = await _player(test_db_session)
        await _land(test_db_session, STARTING)
        nation = await seed_nation(
            test_db_session, player, province_ids=STARTING, legacy=True
        )

        with pytest.raises(CapitalNotInProvincesError):
            await NationService.update(
                test_db_session,
                nation.id,
                capital_name="Newburg",
                config=config,
            )


class TestColorCheckEndpoint:
    """POST /api/v1/nations/color-check — read-only hint (Part 5)."""

    async def test_statuses_and_self_exclusion(self, client, test_db_session):
        player_a = await seed_player(test_db_session, vk_user_id=520001)
        player_b = await seed_player(test_db_session, vk_user_id=520002)
        await seed_provinces(test_db_session, STARTING)
        await seed_nation(
            test_db_session,
            player_a,
            color_hex=COLOR_A,
            province_ids=STARTING,
        )
        url = "/api/v1/nations/color-check"

        # Fresh player's own checks.
        resp = await client.post(
            url,
            headers=bearer_headers(player_b.id),
            json={"color_hex": COLOR_C},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "OK"}

        resp = await client.post(
            url,
            headers=bearer_headers(player_b.id),
            json={"color_hex": COLOR_A},
        )
        assert resp.json() == {"status": "TAKEN"}

        resp = await client.post(
            url,
            headers=bearer_headers(player_b.id),
            json={"color_hex": "#0C7DF5"},
        )
        assert resp.json() == {"status": "TOO_CLOSE"}

        resp = await client.post(
            url,
            headers=bearer_headers(player_b.id),
            json={"color_hex": "#141E26"},  # the reserved sea color
        )
        assert resp.json() == {"status": "TOO_CLOSE"}

        # The owner's own color is excluded — it reads as OK.
        resp = await client.post(
            url,
            headers=bearer_headers(player_a.id),
            json={"color_hex": COLOR_A},
        )
        assert resp.json() == {"status": "OK"}

    async def test_bad_hex_is_422(self, client, test_db_session):
        player = await seed_player(test_db_session, vk_user_id=520003)
        resp = await client.post(
            "/api/v1/nations/color-check",
            headers=bearer_headers(player.id),
            json={"color_hex": "0C7CF4"},
        )
        assert resp.status_code == 422


class TestPatchEndpoint:
    """PATCH /api/v1/nations/me — Registration 2.0 fields over HTTP."""

    async def test_optional_clear_and_mandatory_empty(self, client, test_db_session):
        player = await seed_player(test_db_session, vk_user_id=520004)
        await seed_provinces(test_db_session, STARTING)
        nation = await seed_nation(test_db_session, player, province_ids=STARTING)
        await test_db_session.execute(
            sa.update(Nation)
            .where(Nation.id == nation.id)
            .values(motto="Keep or clear", capital_province_id=1001)
        )

        headers = bearer_headers(player.id)
        resp = await client.patch(
            "/api/v1/nations/me", headers=headers, json={"motto": ""}
        )
        assert resp.status_code == 200
        assert resp.json()["motto"] is None

        resp = await client.patch(
            "/api/v1/nations/me", headers=headers, json={"leader_name": ""}
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "LEADER_NAME_INVALID"

        resp = await client.patch(
            "/api/v1/nations/me",
            headers=headers,
            json={"capital_name": "Newburg"},
        )
        assert resp.status_code == 200
        assert resp.json()["capital_name"] == "Newburg"


# --- Migration 0011 ------------------------------------------------------

_NEW_COLUMNS = [
    "short_name",
    "gender",
    "succession_type",
    "motto",
    "description",
    "leader_bio",
    "flag_id",
    "portrait_id",
    "anthem_url",
    "capital_province_id",
    "capital_name",
]


def _db_url(tmp_path: Path, name: str = "mig.db") -> str:
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _upgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def _downgrade(url: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.downgrade(Config(str(BACKEND_DIR / "alembic.ini")), target)


def test_migration_0011_up_down_up(tmp_path, monkeypatch):
    """0011 adds exactly the eleven columns (all NULLABLE — the legacy
    row survives untouched), the named UNIQUE on short_name and the
    named capital FK; the downgrade removes only those columns."""
    url = _db_url(tmp_path)
    _upgrade(url, "0010", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            nation_id = str(uuid.uuid4())
            player_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO players (id, vk_user_id, created_at) "
                    "VALUES (:id, 42424301, '2026-10-01 00:00:00')"
                ),
                {"id": player_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO nations (id, owner_player_id, name, "
                    "color_hex, created_at, created_turn) "
                    "VALUES (:id, :owner, 'Old Realm', '#0C7CF4', "
                    "'2026-10-01 00:00:00', 3)"
                ),
                {"id": nation_id, "owner": player_id},
            )
    finally:
        engine.dispose()

    _upgrade(url, "head", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            insp = sa.inspect(conn)
            columns = {c["name"]: c for c in insp.get_columns("nations")}
            assert set(_NEW_COLUMNS) <= set(columns)
            for name in _NEW_COLUMNS:
                assert columns[name]["nullable"] is True

            uniques = {u["name"] for u in insp.get_unique_constraints("nations")}
            assert "uq_nations_short_name" in uniques

            fks = insp.get_foreign_keys("nations")
            capital_fk = next(
                f for f in fks if f["name"] == "fk_nations_capital_province_id"
            )
            assert capital_fk["referred_table"] == "provinces"
            assert capital_fk["constrained_columns"] == ["capital_province_id"]
            assert capital_fk["options"].get("ondelete") == "SET NULL"

            row = (
                conn.execute(
                    sa.text(
                        "SELECT name, color_hex, created_turn, short_name, "
                        "capital_province_id FROM nations WHERE id = :id"
                    ),
                    {"id": nation_id},
                )
                .mappings()
                .one()
            )
            # Existing data untouched; new fields NULL (INV-11 legacy).
            assert row["name"] == "Old Realm"
            assert row["color_hex"] == "#0C7CF4"
            assert row["created_turn"] == 3
            assert row["short_name"] is None
            assert row["capital_province_id"] is None
    finally:
        engine.dispose()

    _downgrade(url, "0010", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            columns = {c["name"] for c in sa.inspect(conn).get_columns("nations")}
            assert set(_NEW_COLUMNS).isdisjoint(columns)
            # The old row is still there, still intact.
            name = conn.execute(
                sa.text("SELECT name FROM nations WHERE id = :id"),
                {"id": nation_id},
            ).scalar_one()
            assert name == "Old Realm"
    finally:
        engine.dispose()

    _upgrade(url, "head", monkeypatch)

    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            columns = {c["name"] for c in sa.inspect(conn).get_columns("nations")}
            assert set(_NEW_COLUMNS) <= columns
    finally:
        engine.dispose()
