"""
Domain exceptions for module 00_core.

These exceptions map to the error codes defined in the API specification
and are raised by domain services when business rules are violated.
"""


class CoreDomainError(Exception):
    """Base exception for all 00_core domain errors."""

    def __init__(
        self, message: str, code: str, details: dict | None = None
    ):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(message)


class NameTakenError(CoreDomainError):
    """Raised when attempting to create a nation with a name that already exists."""
    
    def __init__(self, name: str):
        super().__init__(
            f"Nation name '{name}' is already taken",
            "NAME_TAKEN"
        )


class ColorTakenError(CoreDomainError):
    """Raised when attempting to create a nation with a color that already exists."""
    
    def __init__(self, color_hex: str):
        super().__init__(
            f"Color '{color_hex}' is already taken",
            "COLOR_TAKEN"
        )


class ProvinceTakenError(CoreDomainError):
    """Raised when attempting to assign a province that is already owned."""
    
    def __init__(self, province_id: int):
        super().__init__(
            f"Province {province_id} is already owned by another nation",
            "PROVINCE_TAKEN"
        )


class ProvinceNotFoundError(CoreDomainError):
    """Raised when attempting to assign a province that does not exist."""
    
    def __init__(self, province_id: int):
        super().__init__(
            f"Province {province_id} does not exist",
            "PROVINCE_NOT_FOUND"
        )


class ProvinceCountOutOfRangeError(CoreDomainError):
    """Raised when the number of provinces violates min/max constraints."""
    
    def __init__(self, count: int, min_allowed: int, max_allowed: int):
        super().__init__(
            f"Province count {count} is out of range (must be between {min_allowed} and {max_allowed})",
            "PROVINCE_COUNT_OUT_OF_RANGE"
        )


class NationAlreadyExistsError(CoreDomainError):
    """Raised when attempting to create a nation for a player who already has one."""
    
    def __init__(self, player_id: str):
        super().__init__(
            f"Player {player_id} already owns a nation",
            "NATION_ALREADY_EXISTS"
        )


class NationNotFoundError(CoreDomainError):
    """Raised when attempting to operate on a nation that does not exist."""
    
    def __init__(self, nation_id: str):
        super().__init__(
            f"Nation {nation_id} does not exist",
            "NATION_NOT_FOUND"
        )


class LeaderNameInvalidError(CoreDomainError):
    """Raised when the leader name fails the Part 3 text-field checks."""

    def __init__(self, reason: str):
        super().__init__(
            f"Leader name is invalid: {reason}",
            "LEADER_NAME_INVALID"
        )


class LeaderTitleInvalidError(CoreDomainError):
    """Raised when the leader title fails the Part 3 text-field checks."""

    def __init__(self, reason: str):
        super().__init__(
            f"Leader title is invalid: {reason}",
            "LEADER_TITLE_INVALID"
        )


class HistoryUrlInvalidError(CoreDomainError):
    """Raised when the history URL fails the Part 3 link checks."""

    def __init__(self, reason: str):
        super().__init__(
            f"History URL is invalid: {reason}",
            "HISTORY_URL_INVALID"
        )


class RetiredProvinceOwnedError(CoreDomainError):
    """A retired map node still belongs to a nation (INV-M5, Spec 1.9).

    Raised by ``ProvinceService.remove_retired`` — the startup aborts and
    the message names the provinces and their nations so the world can be
    reset or the nations deleted first.
    """

    def __init__(self, owned: list[tuple[int, str, str | None]]):
        listed = ", ".join(
            f"province {pid} -> nation {nid} ({name})"
            for pid, nid, name in owned
        )
        super().__init__(
            f"Retired map nodes are still owned: {listed} — delete these "
            "nations or reset the world first",
            "RETIRED_PROVINCE_OWNED",
            details={
                "owned": [
                    {
                        "province_id": pid,
                        "nation_id": nid,
                        "nation_name": name,
                    }
                    for pid, nid, name in owned
                ]
            },
        )


class RetiredProvinceHistoryError(CoreDomainError):
    """A retired map node still has ownership-journal rows (INV-M5, 1.9).

    The journal is append-only history and must not be touched, and the
    map_ownership_log -> provinces FK forbids deleting a referenced row.
    The only safe resolution is a manual reconcile / world reset.
    """

    def __init__(self, province_ids: list[int]):
        super().__init__(
            f"Retired map nodes still carry ownership-journal history: "
            f"{province_ids} — the journal is append-only, reconcile the "
            "map data or reset the world",
            "RETIRED_PROVINCE_HISTORY",
            details={"province_ids": province_ids},
        )


class FrequencyCapExceededError(CoreDomainError):
    """Raised when an action frequency cap is exceeded."""
    
    def __init__(self, action_type: str, current_count: int, max_allowed: int):
        super().__init__(
            f"Action '{action_type}' frequency cap exceeded: {current_count}/{max_allowed}",
            "FREQUENCY_CAP_EXCEEDED"
        )
