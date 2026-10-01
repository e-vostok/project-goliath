"""
Domain exceptions for module 00_core.

These exceptions map to the error codes defined in the API specification
and are raised by domain services when business rules are violated.
"""


class CoreDomainError(Exception):
    """Base exception for all 00_core domain errors."""
    
    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
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


class FrequencyCapExceededError(CoreDomainError):
    """Raised when an action frequency cap is exceeded."""
    
    def __init__(self, action_type: str, current_count: int, max_allowed: int):
        super().__init__(
            f"Action '{action_type}' frequency cap exceeded: {current_count}/{max_allowed}",
            "FREQUENCY_CAP_EXCEEDED"
        )
