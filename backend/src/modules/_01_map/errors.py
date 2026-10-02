"""Domain errors of the 01_map module (Spec 01_map Part 5)."""

from __future__ import annotations

from collections.abc import Sequence

from modules._00_core.exceptions import CoreDomainError


class MapDomainError(CoreDomainError):
    """Base for 01_map domain errors — reuses the core code/message shape."""


class ProvinceNotLandError(MapDomainError):
    """SEA ids inside the starting group (Part 5: PROVINCE_NOT_LAND, 422)."""

    code = "PROVINCE_NOT_LAND"

    def __init__(self, sea_ids: Sequence[int]):
        shown = sorted(sea_ids)[:5]
        listing = ", ".join(str(i) for i in shown)
        if len(sea_ids) > len(shown):
            listing += f" и ещё {len(sea_ids) - len(shown)}"
        super().__init__(
            f"Морские зоны не могут входить в стартовую группу: {listing}",
            self.code,
        )


class StartingGroupNotConnectedError(MapDomainError):
    """Disconnected starting group (Part 5: STARTING_GROUP_NOT_CONNECTED)."""

    code = "STARTING_GROUP_NOT_CONNECTED"

    def __init__(self, component_count: int):
        super().__init__(
            "Стартовая группа провинций не связна "
            f"(отдельных частей: {component_count})",
            self.code,
            details={"component_count": component_count},
        )
