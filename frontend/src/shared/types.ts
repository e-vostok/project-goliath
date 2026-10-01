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
  name: string;
  color_hex: string;
  owner_player_id: string;
  province_ids: number[];
  /** null only for nations created before the profile migration. */
  leader_name: string | null;
  leader_title: string | null;
  history_url: string | null;
  created_at: string;
}

export interface NationCreateRequest {
  name: string;
  color_hex: string;
  province_ids: number[];
  leader_name: string;
  leader_title: string;
  history_url: string;
}

export interface NationUpdateRequest {
  name?: string | null;
  color_hex?: string | null;
  leader_name?: string | null;
  leader_title?: string | null;
  history_url?: string | null;
}

export interface NationRulesDTO {
  name_min_length: number;
  name_max_length: number;
  leader_name_min_length: number;
  leader_name_max_length: number;
  leader_title_min_length: number;
  leader_title_max_length: number;
  history_url_max_length: number;
  history_url_allowed_hosts: string[];
  min_provinces: number;
  max_provinces: number;
}

export interface NationDeleteRequest {
  confirm: true;
}

export interface ProvinceDTO {
  id: number;
  nation_id: string | null;
}

export interface GameClockDTO {
  current_turn: number;
  game_date: string;
  next_tick_at: string;
}

export interface ErrorResponse {
  detail: string;
  code: string;
}

/* Admin panel DTOs (core/admin router). State-view payloads are defined by
   each module's hook, so `modules` stays loosely typed. */

/** GET /admin/me — the UI's admin probe. */
export interface AdminMeDTO {
  is_admin: boolean;
}

/** One tick_log row (GET /admin/tick-log and nested in tick/run result). */
export interface AdminTickLogEntryDTO {
  id: number;
  turn_number: number;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  error_message: string | null;
}

/** GET /admin/state — state views keyed by module slug. */
export interface AdminStateDTO {
  modules: Record<string, unknown>;
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

/** Error codes emitted by 00_core (Spec Part 5 + router-internal codes). */
export const ErrorCodes = {
  NAME_TAKEN: 'NAME_TAKEN',
  COLOR_TAKEN: 'COLOR_TAKEN',
  PROVINCE_TAKEN: 'PROVINCE_TAKEN',
  PROVINCE_NOT_FOUND: 'PROVINCE_NOT_FOUND',
  PROVINCE_COUNT_OUT_OF_RANGE: 'PROVINCE_COUNT_OUT_OF_RANGE',
  LEADER_NAME_INVALID: 'LEADER_NAME_INVALID',
  LEADER_TITLE_INVALID: 'LEADER_TITLE_INVALID',
  HISTORY_URL_INVALID: 'HISTORY_URL_INVALID',
  NATION_ALREADY_EXISTS: 'NATION_ALREADY_EXISTS',
  NATION_NOT_FOUND: 'NATION_NOT_FOUND',
  INVALID_SIGNATURE: 'INVALID_SIGNATURE',
  TIMESTAMP_EXPIRED: 'TIMESTAMP_EXPIRED',
  GAME_CLOCK_NOT_FOUND: 'GAME_CLOCK_NOT_FOUND',
  FREQUENCY_CAP_EXCEEDED: 'FREQUENCY_CAP_EXCEEDED',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];
