/**
 * Hand-made mini map in API DTO shape (~10 nodes, mirroring
 * backend/tests/fixtures/map_mini): a chain of land provinces, a strait
 * pair, and two sea zones. Numbers are tiny and the rules are NOT the
 * real config values, so a hardcoded client constant would fail tests.
 */

import type {
  MapBordersDTO,
  MapGeometryDTO,
  MapManifestDTO,
  MapStateDTO,
  MapViewRulesDTO,
} from '../types';

export const MINI_RULES: MapViewRulesDTO = {
  // A frame inside the mini view_box [0, 0, 100, 80].
  frame: [10, 10, 60, 50],
  zoom_max: 8.0,
  pan_margin_fraction: 0.1,
  label_min_width_px: 40,
  search_min_chars: 2,
  search_max_results: 4,
  colors: {
    neutral_province: '#8C8C8C',
    sea: '#1E3547',
    outside: '#2A2A2A',
    inland_water: '#1E3547',
    province_border: '#3A3A3A',
    hover: '#FFFFFF',
  },
  hover_fill_opacity: 0.22,
  hover_stroke_enabled: false,
  borders: {
    internal_width: 0.5,
    internal_dash: '4 2',
    internal_opacity: 0.5,
    internal_color: '#3A3A3A',
    state_width: 1.6,
    state_color: '#101014',
    coast_width: 0.8,
    coast_color: '#24262B',
  },
  selection: {
    pulse_min_opacity: 0.12,
    pulse_max_opacity: 0.3,
    pulse_period_s: 2.0,
    picked_opacity: 0.25,
  },
  require_connected_start: true,
  big_window_enabled: true,
  refresh: {
    tick_refresh_delay_seconds: 5,
    tick_refresh_jitter_seconds: 30,
    retry_delay_seconds: 10,
    max_retries: 3,
    stale_after_seconds: 900,
  },
};

export const MINI_MANIFEST: MapManifestDTO = {
  schema_version: 1,
  geometry_version: 'mini01',
  borders_version: 'minib01',
  view_box: [0, 0, 100, 80],
  playable_bbox: [0, 0, 85, 75],
  nodes: [
    { id: 1001, key: 'mini_alpha', kind: 'LAND', name: 'Mini Alpha', name_ru: 'Альфа', anchor: [5, 25], bbox: [0, 20, 10, 30], area: 100 },
    { id: 1002, key: 'mini_beta', kind: 'LAND', name: 'Mini Beta', name_ru: 'Бета', anchor: [15, 25], bbox: [10, 20, 20, 30], area: 100 },
    { id: 1003, key: 'mini_gamma', kind: 'LAND', name: 'Mini Gamma', name_ru: 'Гамма', anchor: [25, 25], bbox: [20, 20, 30, 30], area: 100 },
    { id: 1004, key: 'mini_delta', kind: 'LAND', name: 'Mini Delta', name_ru: 'Дельта', anchor: [35, 25], bbox: [30, 20, 40, 30], area: 100 },
    { id: 1005, key: 'mini_epsilon', kind: 'LAND', name: 'Mini Epsilon', name_ru: 'Эпсилон', anchor: [55, 45], bbox: [50, 40, 60, 50], area: 100 },
    { id: 1006, key: 'mini_zeta', kind: 'LAND', name: 'Mini Zeta', name_ru: 'Дзета', anchor: [66, 45], bbox: [62, 40, 70, 50], area: 80 },
    { id: 1007, key: 'mini_eta', kind: 'LAND', name: 'Mini Eta', name_ru: 'Эта', anchor: [76, 64], bbox: [72, 60, 80, 68], area: 64 },
    { id: 1008, key: 'mini_yolkino', kind: 'LAND', name: 'Mini Yolkino', name_ru: 'Ёлкино', anchor: [37, 9], bbox: [34, 6, 40, 12], area: 36 },
    { id: 2001, key: 'sea_mini_north', kind: 'SEA', name: 'Mini North Sea', name_ru: 'Северное мини-море', anchor: [37, 7], bbox: [28, 0, 46, 14], area: 252 },
    { id: 2002, key: 'sea_mini_south', kind: 'SEA', name: 'Mini South Sea', name_ru: 'Южное мини-море', anchor: [64, 54], bbox: [46, 36, 82, 72], area: 1296 },
  ],
  edges: [
    { a: 1001, b: 1002, type: 'land', name: null, multiplier: null },
    { a: 1002, b: 1003, type: 'land', name: null, multiplier: null },
    { a: 1003, b: 1004, type: 'land', name: null, multiplier: null },
    { a: 1004, b: 2001, type: 'coast', name: null, multiplier: null },
    { a: 1005, b: 1006, type: 'strait', name: 'Мини-пролив', multiplier: 0.5 },
    { a: 1005, b: 2002, type: 'coast', name: null, multiplier: null },
    { a: 1006, b: 1007, type: 'strait', name: 'Малый пролив', multiplier: 0.3 },
    { a: 1007, b: 2002, type: 'coast', name: null, multiplier: null },
    { a: 1008, b: 2001, type: 'coast', name: null, multiplier: null },
    { a: 2001, b: 2002, type: 'sea', name: null, multiplier: null },
  ],
  rules: MINI_RULES,
  attribution: 'Mini fixture, no attribution',
};

export const MINI_GEOMETRY: MapGeometryDTO = {
  version: 'mini01',
  outside: 'M 0 0 L 100 0 L 100 80 L 0 80 Z',
  sea_water: '',
  paths: {
    1001: 'M 0 20 L 10 20 L 10 30 L 0 30 Z',
    1002: 'M 10 20 L 20 20 L 20 30 L 10 30 Z',
    1003: 'M 20 20 L 30 20 L 30 30 L 20 30 Z',
    1004: 'M 30 20 L 40 20 L 40 30 L 30 30 Z',
    1005: 'M 50 40 L 60 40 L 60 50 L 50 50 Z',
    1006: 'M 62 40 L 70 40 L 70 50 L 62 50 Z',
    1007: 'M 72 60 L 80 60 L 80 68 L 72 68 Z',
    1008: 'M 34 6 L 40 6 L 40 12 L 34 12 Z',
    2001: 'M 28 0 L 46 0 L 46 14 L 28 14 Z',
    2002: 'M 46 36 L 82 36 L 82 72 L 46 72 Z',
  },
};

/** Mirrors backend/tests/fixtures/map_mini/borders.json (map2_1B). */
export const MINI_BORDERS: MapBordersDTO = {
  version: 'minib01',
  pairs: {
    '1001-1002': 'M 9.96 20 10 20 10 30 9.96 30',
    '1002-1003': 'M 19.95 20 20 20 20 30 19.97 30',
    '1003-1004': 'M 29.95 20 30 20 30 30 29.97 30',
  },
  coasts: {
    '1001': 'M 9.96 30 0 30 0 20 9.96 20',
    '1002': 'M 10.13 20 19.95 20M 19.97 30 10.13 30',
    '1003': 'M 20.11 20 29.95 20M 29.97 30 20.13 30',
    '1004': 'M 30.11 20 40 20 40 30 30.13 30',
    '1005': 'M 50 40 60 40 60 50 50 50 Z',
    '1006': 'M 62 40 70 40 70 50 62 50 Z',
    '1007': 'M 72 60 80 60 80 68 72 68 Z',
    '1008': 'M 34 6 40 6 40 12 34 12 Z',
  },
};

export const MINI_STATE: MapStateDTO = {
  geometry_version: 'mini01',
  borders_version: 'minib01',
  turn: 7,
  nations: [
    {
      id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
      name: 'Тестия',
      color_hex: '#e64545',
    },
  ],
  owners: [
    [1001, 0],
    [1002, 0],
  ],
};

export const MINI_STATE_EMPTY: MapStateDTO = {
  geometry_version: 'mini01',
  borders_version: 'minib01',
  turn: 7,
  nations: [],
  owners: [],
};
