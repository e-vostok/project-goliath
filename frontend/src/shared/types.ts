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
  created_at: string;
}

export interface NationCreateRequest {
  name: string;
  color_hex: string;
  province_ids: number[];
}

export interface NationUpdateRequest {
  name?: string | null;
  color_hex?: string | null;
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

/** Error codes emitted by 00_core (Spec Part 5 + router-internal codes). */
export const ErrorCodes = {
  NAME_TAKEN: 'NAME_TAKEN',
  COLOR_TAKEN: 'COLOR_TAKEN',
  PROVINCE_TAKEN: 'PROVINCE_TAKEN',
  PROVINCE_NOT_FOUND: 'PROVINCE_NOT_FOUND',
  PROVINCE_COUNT_OUT_OF_RANGE: 'PROVINCE_COUNT_OUT_OF_RANGE',
  NATION_ALREADY_EXISTS: 'NATION_ALREADY_EXISTS',
  NATION_NOT_FOUND: 'NATION_NOT_FOUND',
  INVALID_SIGNATURE: 'INVALID_SIGNATURE',
  TIMESTAMP_EXPIRED: 'TIMESTAMP_EXPIRED',
  GAME_CLOCK_NOT_FOUND: 'GAME_CLOCK_NOT_FOUND',
  FREQUENCY_CAP_EXCEEDED: 'FREQUENCY_CAP_EXCEEDED',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];
