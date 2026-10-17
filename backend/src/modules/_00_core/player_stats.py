"""
Player stat scale constants for module 00_core (Spec 03_registry 0/D1, 1.2).

The scale bounds are properties of the data model, pinned by named
CHECK constraints in migration 0008 — config files can repeat them only
as drawing parameters (e.g. gauge ``scale_min``/``scale_max``), never
change them.
"""

LEVEL_MIN = 1
LEVEL_DEFAULT = 1

JUDGE_RATING_MIN = -100
JUDGE_RATING_MAX = 100
JUDGE_RATING_DEFAULT = 0
