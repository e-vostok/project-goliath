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

/**
 * `node.label` (map2_6): label anchor plus the free `w`/`h` box in map
 * units the client fits the name into (pipeline-computed).
 *
 * `spine`/`len`/`thick` (map2_20): the inscribed baseline the curved
 * name rides — `[x0, y0, x1, y1, s]` chord endpoints plus the signed
 * sagitta (the quadratic Bézier control point is the chord midpoint
 * moved by `2·s` along the chord's left normal), the chord length
 * `len` and the local thickness `thick` across the spine.
 */
export interface MapNodeLabelDTO {
  x: number;
  y: number;
  w: number;
  h: number;
  spine: [number, number, number, number, number];
  len: number;
  thick: number;
}

export interface MapNodeDTO {
  id: number;
  key: string;
  kind: MapNodeKind;
  name: string;
  name_ru: string | null;
  anchor: [number, number];
  bbox: [number, number, number, number];
  area: number;
  label: MapNodeLabelDTO;
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
 * `rules.relief` — grayscale relief underlay (map2_16). Two images
 * live under `/assets/map/` (names from `relief/manifest.json`,
 * content-hashed, cacheable immutable): the bright playable relief and
 * the near-black inactive world; these fields only steer how the
 * playable image is blended and how dark the world was baked.
 */
export interface MapReliefRulesDTO {
  enabled: boolean;
  /** Strength of the relief showing through the playable fills (0..1). */
  strength_playable: number;
  /** Brightness the inactive world relief was baked at (0.02..1). */
  inactive_brightness: number;
}

/**
 * `rules.labels` (map2_6): a name is drawn only if it fits its `label`
 * box at the current zoom; collisions resolve by area priority.
 * `font` (land) and `sea_font` pick from the six bundled self-hosted
 * faces of the map font registry (map2_21). map2_6c:
 * `province_zoom_ratio` of the camera's
 * maximum scale is where province names live (sea names below it);
 * `fade_ms` is the appear/disappear transition (0 = off,
 * prefers-reduced-motion forces 0). map2_20: `max_angle_deg`/`max_bend`/
 * `thickness_ratio`/`length_ratio`/`letter_spacing_*_em`/`land_opacity`
 * drive the curved name along the node's spine; `sea_curved` applies
 * the same mechanism to sea names (their own style is kept).
 */
export interface MapLabelsRulesDTO {
  font:
    | 'share_tech_mono'
    | 'ibm_plex_mono'
    | 'pt_mono'
    | 'fira_sans_condensed'
    | 'pt_sans_narrow'
    | 'roboto_condensed';
  sea_font:
    | 'share_tech_mono'
    | 'ibm_plex_mono'
    | 'pt_mono'
    | 'fira_sans_condensed'
    | 'pt_sans_narrow'
    | 'roboto_condensed';
  land_min_px: number;
  land_max_px: number;
  sea_min_px: number;
  sea_max_px: number;
  fit_ratio: number;
  collision_padding_px: number;
  halo_width_px: number;
  halo_color: string;
  land_color: string;
  sea_color: string;
  sea_letter_spacing_em: number;
  province_zoom_ratio: number;
  fade_ms: number;
  max_angle_deg: number;
  max_bend: number;
  thickness_ratio: number;
  length_ratio: number;
  letter_spacing_min_em: number;
  letter_spacing_max_em: number;
  land_opacity: number;
  sea_curved: boolean;
}

/**
 * `rules.states` (map2_7): one rotated inscription per state, fitted
 * inside its territory, visible at every zoom below the maximum (the
 * `labels.province_zoom_ratio` threshold where province names live).
 * `font` picks from the six bundled faces of the map font registry —
 * the terminal mono cuts keep the «1960s equipment» look (map2_21).
 */
export interface MapStatesRulesDTO {
  font:
    | 'share_tech_mono'
    | 'ibm_plex_mono'
    | 'pt_mono'
    | 'fira_sans_condensed'
    | 'pt_sans_narrow'
    | 'roboto_condensed';
  uppercase: boolean;
  opacity: number;
  max_angle_deg: number;
  thickness_ratio: number;
  length_ratio: number;
  max_letter_spacing_em: number;
  max_bend: number;
  min_px: number;
  max_px: number;
  color_mode: 'auto' | 'light' | 'dark';
  min_group_share: number;
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
  labels: MapLabelsRulesDTO;
  states: MapStatesRulesDTO;
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
