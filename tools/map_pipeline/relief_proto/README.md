# relief_proto — shaded-relief underlay prototype (map_polish_5, stage 1)

Prototype only. Touches no product code. Artifacts go to
`tools/map_pipeline/reference/relief_*` and `relief_proto/registration.json`.
Downloads/intermediates live in `dl/` and `out/` (both gitignored).

## Setup

```
pip install -r tools/map_pipeline/requirements.txt
pip install -r tools/map_pipeline/relief_proto/requirements.txt
```

## Inputs to fetch (not committed)

```
tools/map_pipeline/relief_proto/dl/NE2_HR_LC_SR_W_DR.zip
    https://naciscdn.org/naturalearth/10m/raster/NE2_HR_LC_SR_W_DR.zip
tools/map_pipeline/relief_proto/dl/ne_10m_land.zip
    https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip
```

## Run (from repo root)

```
python -m tools.map_pipeline.relief_proto.register   # fit + registration.json + coast-check pngs
python -m tools.map_pipeline.relief_proto.bake       # relief_texture_{12,16}[_dim].webp + stats
python -m tools.map_pipeline.relief_proto.make_preview
python -m tools.map_pipeline.relief_proto.shots      # needs Chrome/Edge
```

`register` is deterministic given the same inputs (fixed RNG seed);
`bake` writes byte-identical files on re-run (same encoder settings).

## Tunables

All baking constants are at the top of `bake.py` (`RELIEF_CONTRAST`,
`DIM_SATURATION`, `DIM_BRIGHTNESS`, `COAST_BLEED_PX`, `PX_PER_UNIT`).
Registration constants at the top of `register.py`.
