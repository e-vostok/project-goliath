"""
Shared nation profile values for tests (Spec 1.3, INV-7 + INV-12).

Every nation created after the Registration 2.0 migration must carry
all mandatory descriptive fields, so tests spread them into
NationService.create calls and POST /api/v1/nations bodies via
``**VALID_PROFILE``. Tests that register more than one nation in the
same scope must override ``name``/``short_name``/``color_hex`` —
``short_name`` is UNIQUE (INV-11).
"""

from __future__ import annotations

VALID_PROFILE: dict[str, str] = {
    "leader_name": "Ivan Grozny",
    "leader_title": "Supreme Ruler",
    "history_url": "https://vk.com/@goliath-history",
    "short_name": "Testland",
    "gender": "male",
    "succession_type": "elections",
    "capital_name": "Testburg",
}
