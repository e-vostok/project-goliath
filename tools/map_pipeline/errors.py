"""Error types and stable error codes for the map pipeline tool.

Every failure raised by the pipeline carries a stable ``code`` so that a human
or another tool can react to it without parsing free-form text. Independent
errors are collected into a single :class:`PipelineFailure` and reported as one
``CODE: message`` block each.
"""
from __future__ import annotations

import sys

# Stable error codes used by this tool.
CONFIG_INVALID = "CONFIG_INVALID"
DATA_INVALID = "DATA_INVALID"
UNSUPPORTED_TRANSFORM = "UNSUPPORTED_TRANSFORM"
DUPLICATE_ID = "DUPLICATE_ID"
BOUNDARY_UNKNOWN_ID = "BOUNDARY_UNKNOWN_ID"
KEY_INVALID = "KEY_INVALID"
KEY_COLLISION = "KEY_COLLISION"
DROP_PART_NOT_FOUND = "DROP_PART_NOT_FOUND"
DROP_PART_EMPTIES_PROVINCE = "DROP_PART_EMPTIES_PROVINCE"
ISOLATED_PART = "ISOLATED_PART"
KEY_REMOVED = "KEY_REMOVED"
IDS_LOCK_INVALID = "IDS_LOCK_INVALID"
PATCH_INVALID = "PATCH_INVALID"
# MP-2: sea zones and the node graph.
SEED_OUTSIDE_WATER = "SEED_OUTSIDE_WATER"
ZONE_EMPTY = "ZONE_EMPTY"
UNSEEDED_WATER = "UNSEEDED_WATER"
WATER_OUTSIDE_INVALID = "WATER_OUTSIDE_INVALID"
EDGE_UNKNOWN_NODE = "EDGE_UNKNOWN_NODE"
EDGE_TYPE_MISMATCH = "EDGE_TYPE_MISMATCH"
EDGE_REMOVE_NOT_FOUND = "EDGE_REMOVE_NOT_FOUND"
STRAIT_ALREADY_CONNECTED = "STRAIT_ALREADY_CONNECTED"
LAND_LINK_ALREADY_CONNECTED = "LAND_LINK_ALREADY_CONNECTED"
GRAPH_DISCONNECTED = "GRAPH_DISCONNECTED"
GRAPH_INVARIANT = "GRAPH_INVARIANT"
# MP-3: geometry, manifest and preview.
VIEWBOX_MISMATCH = "VIEWBOX_MISMATCH"
GEOMETRY_EMPTY = "GEOMETRY_EMPTY"
GEOMETRY_INVALID = "GEOMETRY_INVALID"
GEOMETRY_TOO_LARGE = "GEOMETRY_TOO_LARGE"
MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
NODE_DEGREE_LIMIT = "NODE_DEGREE_LIMIT"
NODES_LIMIT = "NODES_LIMIT"
MANIFEST_INVALID = "MANIFEST_INVALID"
# MP-3 (map2_1B): canonical shared borders and coasts.
BORDERS_NO_SEGMENT = "BORDERS_NO_SEGMENT"
BORDERS_COVERAGE = "BORDERS_COVERAGE"
BORDERS_TOO_LARGE = "BORDERS_TOO_LARGE"


class PipelineError(Exception):
    """A single pipeline failure with a stable code."""

    def __init__(
        self,
        code: str,
        message: str,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = list(details or [])


class PipelineFailure(Exception):
    """Aggregates several independent :class:`PipelineError` items."""

    def __init__(self, errors: list[PipelineError]) -> None:
        self.errors = list(errors)
        super().__init__(f"{len(self.errors)} pipeline error(s)")


def print_errors(errors: list[PipelineError]) -> None:
    """Print one ``CODE: message`` block per error to stderr."""
    for err in errors:
        print(f"{err.code}: {err.message}", file=sys.stderr)
        for line in err.details:
            print(f"  {line}", file=sys.stderr)
