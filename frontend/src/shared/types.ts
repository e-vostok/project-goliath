/**
 * DTO types for module 00_core.
 *
 * Mirrors backend/src/modules/_00_core/schemas.py field-for-field.
 * `datetime`/`UUID` serialize as JSON strings; keep them `string` here.
 */

export interface VkAuthRequest {
  launch_params: string;
}

export interface PlayerDTO {
  id: string;
  vk_user_id: number;
  created_at: string;
}

export interface AuthResponseDTO {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  player: PlayerDTO;
}

export interface NationDTO {
  id: string;
  owner_player_id: string;
  created_at: string;
  name: string;
  /** Mandatory — the column is NOT NULL since migration 0012. */
  short_name: string;
  color_hex: string;
  motto: string | null;
  description: string | null;
  flag_id: string | null;
  flag_url: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string | null;
  /** null only for nations created before the profile migration. */
  leader_name: string | null;
  gender: string | null;
  leader_title: string | null;
  leader_bio: string | null;
  portrait_id: string | null;
  portrait_url: string | null;
  succession_type: string | null;
  history_url: string | null;
  anthem_url: string | null;
  /** Owner's player stats — since 0.9.0 (unit 14). */
  level: number;
  judge_rating: number;
}

/**
 * The public view of another player's nation (Bible §7, Spec Part 5) —
 * exactly the 20 keys the server sends; the service fields
 * (`owner_player_id`, `gender`, `succession_type`, `anthem_url`) and VK
 * identifiers are never part of it.
 */
export interface NationPublicDTO {
  id: string;
  created_at: string;
  name: string;
  short_name: string;
  color_hex: string;
  motto: string | null;
  description: string | null;
  flag_id: string | null;
  flag_url: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string | null;
  leader_name: string | null;
  leader_title: string | null;
  leader_bio: string | null;
  portrait_id: string | null;
  portrait_url: string | null;
  history_url: string | null;
  level: number;
  judge_rating: number;
}

export interface NationCreateRequest {
  name: string;
  short_name: string;
  color_hex: string;
  motto: string | null;
  description: string | null;
  flag_id: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string;
  leader_name: string;
  gender: string;
  leader_title: string;
  leader_bio: string | null;
  portrait_id: string | null;
  succession_type: string;
  history_url: string;
  anthem_url: string | null;
}

export interface NationUpdateRequest {
  name?: string | null;
  short_name?: string | null;
  color_hex?: string | null;
  motto?: string | null;
  description?: string | null;
  flag_id?: string | null;
  capital_name?: string | null;
  leader_name?: string | null;
  gender?: string | null;
  leader_title?: string | null;
  leader_bio?: string | null;
  portrait_id?: string | null;
  succession_type?: string | null;
  history_url?: string | null;
  anthem_url?: string | null;
}

export interface CatalogItemDTO {
  id: string;
  url: string;
}

export interface NationRulesDTO {
  name_min_length: number;
  name_max_length: number;
  short_name_min_length: number;
  short_name_max_length: number;
  motto_max_length: number;
  description_max_length: number;
  leader_name_min_length: number;
  leader_name_max_length: number;
  leader_title_min_length: number;
  leader_title_max_length: number;
  leader_bio_max_length: number;
  capital_name_min_length: number;
  capital_name_max_length: number;
  history_url_max_length: number;
  history_url_allowed_hosts: string[];
  anthem_url_max_length: number;
  anthem_url_allowed_hosts: string[];
  min_provinces: number;
  max_provinces: number;
  palette: string[];
  flags: CatalogItemDTO[];
  portraits: CatalogItemDTO[];
  genders: string[];
  succession_types: string[];
}

export interface ColorCheckRequest {
  color_hex: string;
}

export interface ColorCheckDTO {
  status: 'OK' | 'TAKEN' | 'TOO_CLOSE';
}

export interface ProvinceDTO {
  id: number;
  nation_id: string | null;
}

export interface GameClockDTO {
  current_turn: number;
  game_date: string;
  game_date_text: string;
  next_tick_at: string;
}

export interface ErrorResponse {
  detail: string;
  code: string;
}

/* Admin panel DTOs (core/admin router). State-view payloads are defined by
   each module's hook, so `modules` stays loosely typed. */

/**
 * GET /admin/me — the UI's admin probe. `reset_allowed` is the
 * request-time ADMIN_ALLOW_RESET read: the panel keeps the world-reset
 * button disabled while it is false.
 */
export interface AdminMeDTO {
  is_admin: boolean;
  reset_allowed: boolean;
}

/**
 * POST /admin/panel-link — the one-time link token. It goes into the
 * panel page's `#t=` fragment and lives `expires_in_seconds`.
 */
export interface AdminPanelLinkDTO {
  token: string;
  expires_in_seconds: number;
}

/** POST /admin/session request — the one-time link token from `#t=`. */
export interface AdminSessionRequest {
  token: string;
}

/**
 * POST /admin/session response — the short panel Bearer session.
 * `expires_in_seconds` counts from the exchange answer.
 */
export interface AdminSessionDTO {
  access_token: string;
  expires_in_seconds: number;
}

/** One tick_log row (GET /admin/tick-log and nested in tick/run result). */
export interface AdminTickLogEntryDTO {
  id: number;
  turn_number: number;
  /** «1 · январь 2040» — server-derived game date of the turn. */
  turn_label: string;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  error_message: string | null;
}

/**
 * One «Состояние мира» tile (GET /admin/overview): every module's
 * overview hook contributes its tiles; `value` arrives already
 * formatted for display, `sort` is the merged cross-module order.
 */
export interface AdminOverviewTileDTO {
  key: string;
  label: string;
  value: string;
  sort: number;
}

/** POST /admin/tick/run result. tick_log is null when no row exists. */
export interface AdminTickRunResultDTO {
  ok: boolean;
  current_turn: number;
  next_tick_at: string | null;
  tick_log: AdminTickLogEntryDTO | null;
}

/** POST /admin/state/reset result — module slugs that were reset. */
export interface AdminResetResultDTO {
  reset: string[];
}

/**
 * GET /admin/players/{vk_user_id}/delete-preview and the matching POST
 * /delete result — the fixed-shape "what disappears with this player"
 * counts assembled from every module's preview hook.
 */
export interface AdminPlayerDeleteResultDTO {
  vk_user_id: number;
  nation_name: string | null;
  provinces_released: number;
  orders_author: number;
  orders_judge_undecided: number;
  orders_judge_decided: number;
  outbox_rows: number;
  consent_rows: number;
  vk_profile_rows: number;
}

/** One row of GET /admin/players — the panel's «Игроки» table. */
export interface AdminPlayerDTO {
  vk_user_id: number;
  /** Hook-assembled display name (the VK profile cache); null when unknown. */
  display_name: string | null;
  /** The player's nation's short name; null for a nationless player. */
  nation_short_name: string | null;
  /** 'YYYY-MM-DD HH:MM:SS' in the tick timezone, like every admin answer. */
  created_at: string;
  is_admin: boolean;
}

/** GET /admin/players — one page plus the full matching count. */
export interface AdminPlayersDTO {
  items: AdminPlayerDTO[];
  total: number;
}

/** Error codes emitted by 00_core (Spec Part 5 + router-internal codes). */
export const ErrorCodes = {
  NAME_TAKEN: 'NAME_TAKEN',
  SHORT_NAME_TAKEN: 'SHORT_NAME_TAKEN',
  COLOR_TAKEN: 'COLOR_TAKEN',
  COLOR_TOO_CLOSE: 'COLOR_TOO_CLOSE',
  PROVINCE_TAKEN: 'PROVINCE_TAKEN',
  PROVINCE_NOT_FOUND: 'PROVINCE_NOT_FOUND',
  PROVINCE_COUNT_OUT_OF_RANGE: 'PROVINCE_COUNT_OUT_OF_RANGE',
  NATION_ALREADY_EXISTS: 'NATION_ALREADY_EXISTS',
  NATION_NOT_FOUND: 'NATION_NOT_FOUND',
  LEADER_NAME_INVALID: 'LEADER_NAME_INVALID',
  LEADER_TITLE_INVALID: 'LEADER_TITLE_INVALID',
  GENDER_INVALID: 'GENDER_INVALID',
  SUCCESSION_INVALID: 'SUCCESSION_INVALID',
  SHORT_NAME_INVALID: 'SHORT_NAME_INVALID',
  MOTTO_INVALID: 'MOTTO_INVALID',
  DESCRIPTION_INVALID: 'DESCRIPTION_INVALID',
  LEADER_BIO_INVALID: 'LEADER_BIO_INVALID',
  FLAG_INVALID: 'FLAG_INVALID',
  PORTRAIT_INVALID: 'PORTRAIT_INVALID',
  HISTORY_URL_INVALID: 'HISTORY_URL_INVALID',
  ANTHEM_URL_INVALID: 'ANTHEM_URL_INVALID',
  CAPITAL_NAME_INVALID: 'CAPITAL_NAME_INVALID',
  CAPITAL_NOT_IN_PROVINCES: 'CAPITAL_NOT_IN_PROVINCES',
  INVALID_SIGNATURE: 'INVALID_SIGNATURE',
  TIMESTAMP_EXPIRED: 'TIMESTAMP_EXPIRED',
  UNAUTHORIZED: 'UNAUTHORIZED',
  GAME_CLOCK_NOT_FOUND: 'GAME_CLOCK_NOT_FOUND',
  FREQUENCY_CAP_EXCEEDED: 'FREQUENCY_CAP_EXCEEDED',
  PANEL_LINK_INVALID: 'PANEL_LINK_INVALID',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];
