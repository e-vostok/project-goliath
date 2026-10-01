"""
Shared security infrastructure.

Provides VK launch-params signature validation, JWT session tokens,
and the get_current_player FastAPI dependency reused by every module's
protected routes.
"""


class SecurityError(Exception):
    """Base exception for authentication/authorization failures.

    Mirrors the CoreDomainError contract (message + machine-readable code)
    so the global exception handler in main.py can map both hierarchies
    to ErrorResponse JSON.
    """

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)
