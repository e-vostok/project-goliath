"""Phase-A prototype (map2_1): ONE canonical line per land-neighbour pair.

Reads the shipped ``manifest.json`` + ``geometry.json``, assigns every
point of every land-node contour to a declared ``land`` neighbour or to
the node's coast, derives candidate canonical borders by two methods
(lower-id owner contour vs. band midline), measures junction quality,
perimeter coverage, fill distance and output sizes, and writes reference
previews under ``tools/map_pipeline/reference/borders_*``.

Prototype only: imports shared modules read-only, writes nothing into
``data/``; the pipeline itself is untouched.
"""
