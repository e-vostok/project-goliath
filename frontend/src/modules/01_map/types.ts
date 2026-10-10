/**
 * DTO types for module 01_map.
 *
 * Mirrors backend/src/modules/_01_map/schemas.py field-for-field — these
 * are the wire shapes of GET /api/v1/map/* (Spec Part 5), NOT the raw
 * files in data/map/ (edges carry the final `multiplier`, not `len`;
 * nodes carry no `source_name`; the manifest gains `rules` and
 * `attribution`).
 */

export type MapNodeKind = 'LAND' | 'SEA';
export type MapEdgeType = 'land' | 'coast' | 'sea' | 'strait';

export interface MapNodeDTO {
  id: number;
  key: string;
  kind: MapNodeKind;
  name: string;
  name_ru: string | null;
  anchor: [number, number];
  bbox: [number, number, number, number];
  area: number;
}

export interface MapEdgeDTO {
  a: number;
  b: number;
  type: MapEdgeType;
  name: string | null;
  /** Final strait crossing multiplier (Spec 3.11); null for other types. */
  multiplier: number | null;
}

export interface MapRefreshRulesDTO {
  tick_refresh_delay_seconds: number;
  tick_refresh_jitter_seconds: number;
  retry_delay_seconds: number;
  max_retries: number;
  stale_after_seconds: number;
}

/** `rules.borders` — style of the shared-border layer (map2_4). */
export interface MapBordersRulesDTO {
  internal_width: number;
  internal_opacity: number;
  internal_color: string;
  state_width: number;
  state_color: string;
  coast_width: number;
  coast_color: string;
}

/** `rules.selection` — white selection overlay style (map2_4). */
export interface MapSelectionRulesDTO {
  pulse_min_opacity: number;
  pulse_max_opacity: number;
  pulse_period_s: number;
  picked_opacity: number;
}

/**
 * `rules.relief` — grayscale relief underlay (map2_5). The image
 * itself lives under `/assets/map/` (name from `relief/manifest.json`,
 * content-hashed, cacheable immutable); these fields only steer how it
 * is blended, dimmed and faded. `margin_units`/`edge_fade_units` are
 * bake-time inputs, carried for transparency.
 */
export interface MapReliefRulesDTO {
  enabled: boolean;
  margin_units: number;
  /** Strength of the relief showing through the playable fills (0..1). */
  strength_playable: number;
  /** Opacity of the dimming tint over non-province land (0..1). */
  inactive_opacity: number;
  inactive_tint: string;
  edge_fade_units: number;
}

export interface MapViewRulesDTO {
  /** [x, y, width, height] in view_box units — Spec 3.8 zoom-out frame. */
  frame: [number, number, number, number];
  zoom_max: number;
  pan_margin_fraction: number;
  label_min_width_px: number;
  search_min_chars: number;
  search_max_results: number;
  colors: Record<string, string>;
  /** Translucent `colors.hover` fill of the hovered node (map2_0). */
  hover_fill_opacity: number;
  /** Also stroke the hovered node when true (off by default). */
  hover_stroke_enabled: boolean;
  borders: MapBordersRulesDTO;
  selection: MapSelectionRulesDTO;
  relief: MapReliefRulesDTO;
  require_connected_start: boolean;
  big_window_enabled: boolean;
  refresh: MapRefreshRulesDTO;
}

export interface MapManifestDTO {
  schema_version: number;
  geometry_version: string;
  /** Version of GET /map/borders/{version} (map2_1B). */
  borders_version: string;
  view_box: [number, number, number, number];
  playable_bbox: [number, number, number, number];
  nodes: MapNodeDTO[];
  edges: MapEdgeDTO[];
  rules: MapViewRulesDTO;
  attribution: string;
}

export interface MapGeometryDTO {
  version: string;
  paths: Record<number, string>;
  outside: string;
  /** Compound path of bays/fjords drawn in `colors.sea` (Spec 1.9, 5a). */
  sea_water: string;
}

/**
 * Shared borders of one version (map2_1B): `pairs` keyed `"a-b"` holds
 * the land border between two adjacent nodes, `coasts` keyed by node id
 * holds that node's coastline (sea, excluded land, map edge). Path
 * values are open polylines, not closed fills.
 */
export interface MapBordersDTO {
  version: string;
  pairs: Record<string, string>;
  coasts: Record<string, string>;
}

export interface MapNationDTO {
  id: string | null;
  name: string;
  color_hex: string;
}

export interface MapStateDTO {
  geometry_version: string;
  borders_version: string;
  turn: number;
  nations: MapNationDTO[];
  /** [province_id, index into nations]; free provinces and SEA are absent. */
  owners: [number, number][];
}

/** POST /map/starting-group/check answer (Spec Part 5, Issue 6). */
export interface StartingGroupCheckDTO {
  connected: boolean;
  component_count: number;
}
