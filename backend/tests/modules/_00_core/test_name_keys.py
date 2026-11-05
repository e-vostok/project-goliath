"""
Case- and ё-insensitive nation names (0.14.0 unit 3b).

``name_key`` unit vectors, then the service-level contract on the real
in-memory DB (Anti-Mock Guard): once «Рим» exists, «РИМ» and «рим» are
rejected as full and as short name, «Берёза» blocks «Береза», a PENDING
application reserves its keys for create and for a second submit —
while renaming one's own nation to another case stays allowed and the
accept path excludes the application's own reserve. The displayed name
still stores exactly what the player typed.
"""

from __future__ import annotations

import pytest

from modules._00_core.application_service import ApplicationService
from modules._00_core.config_schema import CoreConfig
from modules._00_core.exceptions import NameTakenError, ShortNameTakenError
from modules._00_core.models import Nation, Player
from modules._00_core.name_keys import name_key
from modules._00_core.service import NationService
from tests.fixtures.profile import VALID_PROFILE
from tests.fixtures.provinces import (
    STARTING_GROUP,
    make_land_province,
    make_starting_group,
)

CORE_CONFIG = CoreConfig.from_yaml(CoreConfig.get_default_config_path())

SECOND_GROUP = [1010, 1011, 1012, 1013, 1014]
COLOR_A = "#0C7CF4"
COLOR_B = "#6A3446"

_DRAFT = {
    **{
        k: v
        for k, v in VALID_PROFILE.items()
        if k not in ("short_name", "capital_name")
    },
    "name": "Анкетия",
    "short_name": "Анкетия",
    "color_hex": COLOR_A,
    "province_ids": list(STARTING_GROUP),
    "capital_province_id": None,
    "capital_name": "Черновск",
}


@pytest.fixture
def config() -> CoreConfig:
    return CORE_CONFIG


async def _player(session, vk_user_id: int) -> Player:
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
        "color_hex": COLOR_B,
        "province_ids": SECOND_GROUP,
        **VALID_PROFILE,
        **overrides,
    }
    return await NationService.create(session, config=config, **kwargs)


class TestNameKey:
    """The pure function: NFKC, whitespace collapse, casefold, ё → е."""

    def test_case_and_space_variants_share_one_key(self):
        assert name_key("Рим") == name_key("РИМ") == name_key(" рим ") == "рим"
        assert name_key("Новый  Рим") == name_key("новый рим") == "новый рим"
        assert name_key("Rome") == name_key("ROME") == "rome"

    def test_yo_folds_to_ye(self):
        assert name_key("Берёза") == name_key("Береза") == "береза"

    def test_different_names_stay_different(self):
        assert name_key("Рим") != name_key("Римма")
        assert name_key("Берёза") != name_key("Берёзка")


class TestNationNameKeys:
    """create/update compare keys, not displayed strings (INV-2/INV-11)."""

    @pytest.mark.asyncio
    async def test_create_rejects_case_and_yo_variants(
        self, test_db_session, config
    ):
        player_a = await _player(test_db_session, 710001)
        player_b = await _player(test_db_session, 710002)
        player_c = await _player(test_db_session, 710003)
        await _land(
            test_db_session,
            list(STARTING_GROUP) + SECOND_GROUP + [1020, 1021, 1022, 1023, 1024],
        )
        await _create(
            test_db_session,
            player_a,
            config,
            name="Рим",
            short_name="Рим",
            color_hex=COLOR_A,
            province_ids=list(STARTING_GROUP),
        )

        with pytest.raises(NameTakenError):
            await _create(test_db_session, player_b, config, name="РИМ")
        with pytest.raises(ShortNameTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Second Realm",
                short_name="рим",
            )

        nation_c = await _create(
            test_db_session,
            player_b,
            config,
            name="Берёза",
            province_ids=[1020, 1021, 1022, 1023, 1024],
        )
        assert nation_c.name_key == "береза"
        with pytest.raises(NameTakenError):
            await _create(
                test_db_session,
                player_c,
                config,
                name="Береза",
                province_ids=SECOND_GROUP,
            )

    @pytest.mark.asyncio
    async def test_rename_to_other_nations_case_variant_is_rejected(
        self, test_db_session, config
    ):
        player_a = await _player(test_db_session, 710010)
        player_b = await _player(test_db_session, 710011)
        await _land(
            test_db_session, list(STARTING_GROUP) + SECOND_GROUP
        )
        await _create(
            test_db_session,
            player_a,
            config,
            name="Рим",
            short_name="Рим",
            color_hex=COLOR_A,
            province_ids=list(STARTING_GROUP),
        )
        nation_b = await _create(
            test_db_session, player_b, config, name="Карфаген"
        )

        with pytest.raises(NameTakenError):
            await NationService.update(
                test_db_session, nation_b.id, name="РИМ", config=config
            )
        with pytest.raises(ShortNameTakenError):
            await NationService.update(
                test_db_session, nation_b.id, short_name="рИм", config=config
            )

    @pytest.mark.asyncio
    async def test_rename_own_nation_to_other_case_is_allowed(
        self, test_db_session, config
    ):
        player = await _player(test_db_session, 710020)
        await _land(test_db_session, SECOND_GROUP)
        nation = await _create(
            test_db_session, player, config, name="Рим", short_name="Рим"
        )

        updated = await NationService.update(
            test_db_session, nation.id, name="РИМ", short_name="РИМ",
            config=config,
        )
        # The displayed name takes the new casing; the key is unchanged.
        assert updated.name == "РИМ"
        assert updated.short_name == "РИМ"
        assert updated.name_key == "рим"


class TestApplicationNameKeys:
    """A PENDING application reserves keys (APP-1); its own reserve
    never blocks its own submit or accept."""

    @pytest.mark.asyncio
    async def test_pending_application_reserves_the_key(
        self, test_db_session, config
    ):
        player_a = await _player(test_db_session, 710030)
        player_b = await _player(test_db_session, 710031)
        player_c = await _player(test_db_session, 710032)
        await _land(
            test_db_session, list(STARTING_GROUP) + SECOND_GROUP
        )
        await ApplicationService.save_draft(
            test_db_session, player_a.id, config, **_DRAFT
        )
        await ApplicationService.submit(test_db_session, player_a.id, config)

        # NationService.create sees the reserve through the key.
        with pytest.raises(NameTakenError):
            await _create(
                test_db_session, player_b, config, name="АНКЕТИЯ"
            )
        with pytest.raises(ShortNameTakenError):
            await _create(
                test_db_session,
                player_b,
                config,
                name="Other Realm",
                short_name="анкетия",
            )

        # A second application's submit with a case-variant name is
        # rejected the same way.
        await ApplicationService.save_draft(
            test_db_session,
            player_c.id,
            config,
            **{
                **_DRAFT,
                "name": "анкетИя",
                "short_name": "Второй",
                "color_hex": COLOR_B,
                "province_ids": SECOND_GROUP,
            },
        )
        with pytest.raises(NameTakenError):
            await ApplicationService.submit(
                test_db_session, player_c.id, config
            )

    @pytest.mark.asyncio
    async def test_accept_excludes_the_applications_own_reserve(
        self, test_db_session, config
    ):
        player = await _player(test_db_session, 710040)
        decider = await _player(test_db_session, 710041)
        await _land(test_db_session, list(STARTING_GROUP))
        application = await ApplicationService.save_draft(
            test_db_session, player.id, config, **_DRAFT
        )
        await ApplicationService.submit(test_db_session, player.id, config)

        application, nation = await ApplicationService.accept(
            test_db_session,
            application.id,
            config,
            decided_by_player_id=decider.id,
        )
        assert application.status == "ACCEPTED"
        assert nation.name == "Анкетия"
        assert nation.name_key == "анкетия"
