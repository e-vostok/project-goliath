"""
Code constants for nation descriptive fields (Spec Part 1).

These value sets are fixed in code — they are not balance numbers and
never move into the config. Russian labels are rendered by the client
(Part 5); the server operates on the codes only.
"""

from __future__ import annotations

# «мужской» / «женский» — the gender of the nation's leader.
GENDERS: tuple[str, ...] = ("male", "female")

# «демократические выборы» / «назначение игроком» / «назначение по
# критериям» / «наследование» — how the next leader takes over.
SUCCESSION_TYPES: tuple[str, ...] = (
    "elections",
    "appointment",
    "criteria",
    "inheritance",
)
