"""
Shared nation profile values for tests (Spec 1.1, INV-7).

Every nation created after the profile migration must carry all three
fields, so tests spread them into NationService.create calls and POST
/api/v1/nations bodies via ``**VALID_PROFILE``.
"""

from __future__ import annotations

VALID_PROFILE: dict[str, str] = {
    "leader_name": "Ivan Grozny",
    "leader_title": "Supreme Ruler",
    "history_url": "https://vk.com/@goliath-history",
}
