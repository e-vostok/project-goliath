/**
 * 02_bot API layer — GET /bot/status and POST /bot/consent/refresh
 * (Spec 1.1, п. 5.2). Both endpoints answer the same BotStatusDTO.
 *
 * The server is the source of truth: every number (poll interval, poll
 * timeout) and the chat address come from this response — the client
 * keeps no constants of its own.
 *
 * `toBotStatus` normalizes a raw DTO into the discriminated state the UI
 * consumes. Fail-open (INV-B15): a malformed payload — enabled=true but a
 * missing/non-https chat_url or absent polling parameters — collapses to
 * 'unavailable', which never shows the consent gate or the nation row.
 */

import { apiFetch, ApiError } from '../../shared/api-client';

/** Error codes this module understands (Spec 5.2, п. 3.10). */
export const BotErrorCodes = {
  BOT_DISABLED: 'BOT_DISABLED',
  CONSENT_REQUIRED: 'CONSENT_REQUIRED',
} as const;

export type BotConsent = 'ALLOWED' | 'DENIED' | 'UNKNOWN';

/** Raw response of GET /bot/status and POST /bot/consent/refresh. */
export interface BotStatusDTO {
  enabled: boolean;
  consent: BotConsent;
  /** true = the VK recheck failed, this is the last saved value. */
  stale: boolean;
  /** true = the forced recheck was rate-limited, saved value returned. */
  throttled: boolean;
  registration_requires_consent: boolean;
  chat_url: string | null;
  consent_poll_interval_seconds: number | null;
  consent_poll_timeout_seconds: number | null;
}

/** A status where the bot is enabled and the payload passed validation. */
export interface ReadyBotStatusDTO extends BotStatusDTO {
  enabled: true;
  chat_url: string;
  consent_poll_interval_seconds: number;
  consent_poll_timeout_seconds: number;
}

export type BotStatus =
  | { status: 'loading' }
  | { status: 'disabled' }
  | { status: 'unavailable' }
  | { status: 'ready'; dto: ReadyBotStatusDTO };

function isPositiveSeconds(value: number | null): value is number {
  return (
    typeof value === 'number' && Number.isFinite(value) && value > 0
  );
}

function isReadyDto(dto: BotStatusDTO): dto is ReadyBotStatusDTO {
  return (
    dto.enabled === true &&
    typeof dto.chat_url === 'string' &&
    dto.chat_url.startsWith('https://') &&
    isPositiveSeconds(dto.consent_poll_interval_seconds) &&
    isPositiveSeconds(dto.consent_poll_timeout_seconds)
  );
}

/** Maps a raw DTO to the UI state; never throws, always fails open. */
export function toBotStatus(dto: BotStatusDTO): BotStatus {
  if (!dto.enabled) {
    return { status: 'disabled' };
  }
  if (!isReadyDto(dto)) {
    return { status: 'unavailable' };
  }
  return { status: 'ready', dto };
}

/** POST consent/refresh rejected with 409 BOT_DISABLED — the bot is off. */
export function isBotDisabledError(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.code === BotErrorCodes.BOT_DISABLED
  );
}

/** Registration submit rejected because consent is missing (Spec 3.10). */
export function isConsentRequiredError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.code === BotErrorCodes.CONSENT_REQUIRED
  );
}

/** GET /api/v1/bot/status — notification state + gate parameters. */
export function fetchBotStatus(token: string, signal?: AbortSignal) {
  return apiFetch<BotStatusDTO>('/bot/status', { token, signal });
}

/** POST /api/v1/bot/consent/refresh — forced recheck while the user waits. */
export function refreshConsent(token: string, signal?: AbortSignal) {
  return apiFetch<BotStatusDTO>('/bot/consent/refresh', {
    method: 'POST',
    token,
    signal,
  });
}
