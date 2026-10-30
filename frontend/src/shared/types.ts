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
  flag_url: string | null;
  flag_thumb_url: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string | null;
  /** null only for nations created before the profile migration. */
  leader_name: string | null;
  gender: string | null;
  leader_title: string | null;
  leader_bio: string | null;
  portrait_url: string | null;
  portrait_thumb_url: string | null;
  succession_type: string | null;
  history_url: string | null;
  anthem_url: string | null;
  /** Owner's player stats — since 0.9.0 (unit 14). */
  level: number;
  judge_rating: number;
}

/**
 * The public view of another player's nation (Bible §7, Spec Part 5) —
 * exactly the public keys the server sends; the service fields
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
  flag_url: string | null;
  flag_thumb_url: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string | null;
  leader_name: string | null;
  leader_title: string | null;
  leader_bio: string | null;
  portrait_url: string | null;
  portrait_thumb_url: string | null;
  history_url: string | null;
  level: number;
  judge_rating: number;
}

/** Answer of PUT /nations/me/images/{kind} (Spec Part 5). */
export interface NationImageDTO {
  kind: 'flag' | 'portrait';
  url: string;
  thumb_url: string;
}

export interface NationCreateRequest {
  name: string;
  short_name: string;
  color_hex: string;
  motto: string | null;
  description: string | null;
  province_ids: number[];
  capital_province_id: number | null;
  capital_name: string;
  leader_name: string;
  gender: string;
  leader_title: string;
  leader_bio: string | null;
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
  capital_name?: string | null;
  leader_name?: string | null;
  gender?: string | null;
  leader_title?: string | null;
  leader_bio?: string | null;
  succession_type?: string | null;
  history_url?: string | null;
  anthem_url?: string | null;
}

/** The upload limits inside NationRulesDTO.images (Spec Part 5). */
export interface NationRulesImagesDTO {
  flag_width: number;
  flag_height: number;
  portrait_width: number;
  portrait_height: number;
  max_upload_bytes: number;
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
  images: NationRulesImagesDTO;
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
  /** The player's permanent Registry number; null until the registry issues one. */
  registry_number: number | null;
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

/**
 * One row of GET /admin/provinces (0.11.0 unit 8a) — a LAND map node
 * for the province pickers: the hook-assembled display `name` (null
 * when no module knows one) and the owning nation, if any.
 */
export interface AdminProvinceDTO {
  id: number;
  name: string | null;
  nation_id: string | null;
  nation_short_name: string | null;
  /** The OWNING nation's current flag thumb — null for a free province (u9). */
  flag_thumb_url: string | null;
}

/** GET /admin/provinces — one page plus the full matching count. */
export interface AdminProvincesDTO {
  items: AdminProvinceDTO[];
  total: number;
}

/**
 * GET /admin/provinces/{id}/transfer-preview (0.11.0 unit 9b) — the
 * fixed-shape "what POST /transfer would check and change": the
 * donor (`from_nation`, null for a free province), the receiver
 * (`to_nation`, null previews a release), `seizes` (a province owned
 * by another nation moves), `capital_choice_needed` plus the donor's
 * remaining provinces as `capital_candidates`, the after-counts and
 * the `blocker` the action would hit (null when it would pass).
 */
export interface AdminProvinceTransferPreviewDTO {
  province: { id: number; name: string | null };
  from_nation: {
    id: string;
    short_name: string;
    provinces_count: number;
    capital_province_id: number | null;
    capital_name: string | null;
  } | null;
  to_nation: {
    id: string;
    short_name: string;
    provinces_count: number;
  } | null;
  seizes: boolean;
  capital_choice_needed: boolean;
  capital_candidates: { id: number; name: string | null }[];
  donor_after: number | null;
  receiver_after: number | null;
  blocker: 'ALREADY_OWNER' | 'LAST_PROVINCE' | null;
}

/**
 * POST /admin/provinces/{id}/transfer request — `to_nation_id` null
 * frees the province; `confirm_seize` allows taking a province owned
 * by another nation; `new_capital_province_id` is mandatory when the
 * moved province is the donor's capital.
 */
export interface AdminProvinceTransferRequest {
  to_nation_id: string | null;
  confirm_seize: boolean;
  new_capital_province_id: number | null;
}

/** POST /admin/provinces/{id}/transfer result — the service answer. */
export interface AdminProvinceTransferResultDTO {
  province_id: number;
  previous_nation_id: string | null;
  new_nation_id: string | null;
  new_capital_province_id: number | null;
}

/**
 * One row of GET /admin/nations (0.11.0 unit 8a) — the «Государства»
 * table. `owner_name` is the hook-assembled display name (null when no
 * module knows one); POST /admin/nations answers the same shape.
 */
export interface AdminNationDTO {
  id: string;
  short_name: string;
  name: string;
  owner_vk_user_id: number;
  owner_name: string | null;
  provinces_count: number;
  capital_name: string | null;
  /** Current flag's /images/<sha>/thumb — null without an upload (0.12.0 u9). */
  flag_thumb_url: string | null;
}

/** GET /admin/nations — one page plus the full matching count. */
export interface AdminNationsDTO {
  items: AdminNationDTO[];
  total: number;
}

/**
 * POST /admin/nations request (0.11.0 unit 8a) — the simplified admin
 * creation: no questionnaire, no flag/portrait picks (the server takes
 * no pictures), no capital name (derived from the
 * capital province's map name). `capital_province_id` absent means the
 * first of `province_ids`.
 */
export interface AdminNationCreateRequest {
  owner_vk_user_id: number;
  name: string;
  short_name: string;
  color_hex: string;
  leader_name: string;
  leader_title: string;
  gender: string;
  succession_type: string;
  history_url: string;
  motto: string | null;
  province_ids: number[];
  capital_province_id?: number | null;
}

/**
 * One uploaded-picture entry of AdminNationDetailDTO.images (0.12.0
 * units 8–9): `uploaded_by` is null when the uploading player is gone;
 * `size_bytes` is the stored full WebP length and `width`/`height`
 * the pipeline's target size of the kind.
 */
export interface AdminNationImageEntryDTO {
  url: string;
  thumb_url: string;
  /** ISO 8601 UTC — the real-world upload moment. */
  uploaded_at: string;
  uploaded_by: { vk_user_id: number; name: string | null } | null;
  size_bytes: number;
  width: number;
  height: number;
}

/**
 * GET /admin/nations/{id}/images/{kind}/delete-preview and the POST
 * /delete answer (0.12.0 unit 8) — the picture's stamp and the ready
 * Russian «Что будет» lines, rendered verbatim.
 */
export interface AdminNationImageDeletePreviewDTO {
  nation_id: string;
  short_name: string;
  kind: 'flag' | 'portrait';
  uploaded_at: string;
  uploaded_by: { vk_user_id: number; name: string | null } | null;
  consequences: { code: string; text: string }[];
}

/**
 * GET /admin/nations/{id} and the PATCH answer (0.11.0 unit 8b) —
 * the twelve editable fields plus the read-only owner, capital
 * province and province count. Flag, portrait and provinces are
 * never editable here — `images` (0.12.0 unit 8) only describes the
 * uploads, one entry per kind or null.
 */
export interface AdminNationDetailDTO {
  id: string;
  owner_vk_user_id: number;
  owner_name: string | null;
  capital_province_id: number | null;
  provinces_count: number;
  name: string;
  short_name: string;
  color_hex: string;
  motto: string | null;
  description: string | null;
  leader_name: string | null;
  leader_title: string | null;
  gender: string | null;
  succession_type: string | null;
  leader_bio: string | null;
  history_url: string | null;
  capital_name: string | null;
  /** The nation's uploaded pictures — entry or null per kind (unit 8). */
  images: {
    flag: AdminNationImageEntryDTO | null;
    portrait: AdminNationImageEntryDTO | null;
  };
}

/**
 * GET /admin/nations/{id}/delete-preview and the matching POST
 * /delete answer (0.11.0 unit 8c) — what deleting the nation would
 * do: the owner (who stays a player), the provinces it frees
 * (display names, ordered by name) and every module's ready Russian
 * consequence line merged from the nation-preview hooks.
 */
export interface AdminNationDeletePreviewDTO {
  nation_id: string;
  short_name: string;
  name: string;
  owner_vk_user_id: number;
  owner_name: string | null;
  provinces: { id: number; name: string | null }[];
  consequences: { code: string; text: string }[];
}

/**
 * PATCH /admin/nations/{id} request (0.11.0 unit 8b) — only the
 * changed fields are sent; an absent key means "do not change",
 * '' clears an optional field to NULL (INV-8).
 */
export interface AdminNationUpdateRequest {
  name?: string;
  short_name?: string;
  color_hex?: string;
  motto?: string;
  description?: string;
  leader_name?: string;
  leader_title?: string;
  gender?: string;
  succession_type?: string;
  leader_bio?: string;
  history_url?: string;
  capital_name?: string;
}

/**
 * POST /admin/nations/color-check request (0.11.0 unit 8b) — the
 * panel's own colour probe; `nation_id` excludes the edited nation
 * from the comparison on the edit page.
 */
export interface AdminNationColorCheckRequest {
  color_hex: string;
  nation_id?: string;
}

/**
 * GET /admin/state — the aggregated per-module state views (0.11.0
 * unit 6a). Each hook defines its own payload, so `modules` stays
 * loosely typed; the orders section reads the `04_orders` slice as
 * AdminOrdersStateViewDTO.
 */
export interface AdminStateDTO {
  modules: Record<string, unknown>;
}

/**
 * The `04_orders` slice of GET /admin/state (Spec 5.7): the
 * distribution worker's mode and last pass plus the stage counters —
 * the part of the 6a state view the orders list does not replace.
 */
export interface AdminOrdersStateViewDTO {
  orders_total: number;
  worker_mode: 'RUNNING' | 'STOPPED';
  last_pass_at: string | null;
  stages: { SUBMITTED: number; DISTRIBUTED: number; VERDICT: number };
  overdue_total: number;
  unassigned_total: number;
  oldest_unassigned_age_minutes: number | null;
}

/**
 * One row of GET /admin/orders (0.11.0 unit 10a) — the panel's
 * «Приказы» table. `status` is the derived stage, `overdue` marks an
 * undecided order past its deadline; the author nation fields are the
 * order's snapshot. POST /admin/orders/{n}/judge answers this shape.
 */
export interface AdminOrderDTO {
  number: number;
  title: string;
  author_nation_short_name: string | null;
  author_name: string | null;
  judge_vk_user_id: number | null;
  judge_name: string | null;
  status: 'NO_JUDGE' | 'AWAITING_VERDICT' | 'DECIDED';
  /** 'YYYY-MM-DD HH:MM:SS' in the tick timezone; null when undistributed. */
  deadline_at: string | null;
  overdue: boolean;
  /** The author nation's CURRENT flag by nation_id; a deleted nation → null (u9). */
  flag_thumb_url: string | null;
}

/** GET /admin/orders — one page plus the full matching count. */
export interface AdminOrdersDTO {
  items: AdminOrderDTO[];
  total: number;
}

/**
 * GET /admin/orders/{number}/judge-preview (0.11.0 unit 10a) — the
 * read-only "what POST /judge would check": the current and picked
 * judges, the one `blocker` the service would refuse with (null when
 * it would pass) and the ready Russian `warnings` the panel shows
 * under the fixed lead. `warnings[].text` is rendered verbatim.
 */
export interface AdminOrderJudgePreviewDTO {
  current_judge: { vk_user_id: number | null; name: string | null } | null;
  new_judge: { vk_user_id: number; name: string | null };
  blocker:
    | 'ORDER_ALREADY_DECIDED'
    | 'JUDGE_IS_AUTHOR'
    | 'ALREADY_JUDGE'
    | null;
  warnings: { code: string; text: string }[];
}

/** POST /admin/orders/{number}/judge request — the judge's VK id. */
export interface AdminOrderAssignJudgeRequest {
  judge_vk_user_id: number;
}

/** One admin_audit_log row (GET /admin/audit-log) — the «Журнал» table. */
export interface AdminAuditItemDTO {
  id: number;
  /** 'YYYY-MM-DD HH:MM:SS' in the tick timezone, like every admin answer. */
  created_at: string;
  actor_vk_user_id: number;
  /** Display name while the actor is still a player; null afterwards. */
  actor_name: string | null;
  action: string;
  /** The module-registered Russian label; the raw code when unknown. */
  action_label: string;
  target_type: string | null;
  target_id: string | null;
  summary: string;
}

/**
 * GET /admin/audit-log — one journal page. `next_before_id` is the
 * cursor for «Показать ещё»; null on the last page. `retention_limit`
 * is the current admin_panel.audit_log_max_rows — the caption under
 * the table prints it.
 */
export interface AdminAuditLogDTO {
  items: AdminAuditItemDTO[];
  next_before_id: number | null;
  retention_limit: number;
}

/** GET /admin/audit-log/filters — the two dropdowns' values. */
export interface AdminAuditFiltersDTO {
  actors: { vk_user_id: number; display_name: string | null }[];
  actions: { action: string; action_label: string }[];
}

/**
 * One row of GET /admin/admins: `source` 'env' comes from the server
 * settings (never revocable through the panel), 'grant' was issued in
 * the panel. `is_self` marks the caller's own row.
 */
export interface AdminEntryDTO {
  vk_user_id: number;
  display_name: string | null;
  source: 'env' | 'grant';
  granted_by_vk_user_id: number | null;
  granted_by_name: string | null;
  /** 'YYYY-MM-DD HH:MM:SS' in the tick timezone; null for env rows. */
  granted_at: string | null;
  is_self: boolean;
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
  HISTORY_URL_INVALID: 'HISTORY_URL_INVALID',
  ANTHEM_URL_INVALID: 'ANTHEM_URL_INVALID',
  CAPITAL_NAME_INVALID: 'CAPITAL_NAME_INVALID',
  CAPITAL_NOT_IN_PROVINCES: 'CAPITAL_NOT_IN_PROVINCES',
  IMAGE_TOO_LARGE: 'IMAGE_TOO_LARGE',
  IMAGE_UNSUPPORTED: 'IMAGE_UNSUPPORTED',
  IMAGE_ORIENTATION_INVALID: 'IMAGE_ORIENTATION_INVALID',
  INVALID_SIGNATURE: 'INVALID_SIGNATURE',
  TIMESTAMP_EXPIRED: 'TIMESTAMP_EXPIRED',
  UNAUTHORIZED: 'UNAUTHORIZED',
  GAME_CLOCK_NOT_FOUND: 'GAME_CLOCK_NOT_FOUND',
  FREQUENCY_CAP_EXCEEDED: 'FREQUENCY_CAP_EXCEEDED',
  PANEL_LINK_INVALID: 'PANEL_LINK_INVALID',
} as const;

export type ErrorCode = (typeof ErrorCodes)[keyof typeof ErrorCodes];
