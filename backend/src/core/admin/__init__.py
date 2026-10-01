"""
Admin panel infrastructure.

Provides the AdminRegistry hook registry and the require_admin
authorization dependency for admin-only routes.
"""

from core.admin.registry import AdminRegistry
from core.admin.security import AdminRequiredError, require_admin

__all__ = ["AdminRegistry", "AdminRequiredError", "require_admin"]
