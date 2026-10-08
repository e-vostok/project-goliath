"""One-off read-only diagnosis helpers for map2_9 (three map issues).

Nothing here is pipeline code: scripts read ``data/map/manifest.json`` and
``data/map/geometry.json`` and write reports under
``tools/map_pipeline/reference/diag_*``. Run from the repo root, e.g.

    python -m tools.map_pipeline.diag.issue_a_straits
"""
