/**
 * Refresh schedule — Spec 3.10, pure functions (timestamps in ms).
 *
 * DEVIATION (approved for review): the manifest/state DTOs carry no
 * `next_tick_at`, so the next daily tick boundary is computed locally as
 * the next 00:00 in Europe/Moscow — the project rule for the daily tick.
 * Europe/Moscow is a fixed UTC+3 (no DST since 2014), so a constant
 * offset is correct; it lives ONLY in this file.
 */

import type { MapRefreshRulesDTO } from '../types';

const MOSCOW_OFFSET_MS = 3 * 60 * 60 * 1000;

/**
 * Next 00:00 Europe/Moscow strictly after `now`. Date.UTC rolls month
 * and year boundaries on its own.
 */
export function nextMoscowMidnight(now: number): number {
  const msk = new Date(now + MOSCOW_OFFSET_MS);
  const nextUtc = Date.UTC(
    msk.getUTCFullYear(),
    msk.getUTCMonth(),
    msk.getUTCDate() + 1,
    0,
    0,
    0,
    0,
  );
  return nextUtc - MOSCOW_OFFSET_MS;
}

/**
 * Delay in ms from `now` until the scheduled state request
 * (Spec 3.10): next tick boundary + delay + U(0, jitter).
 * `rand` is injected for tests; defaults to Math.random.
 */
export function msUntilStateRefresh(
  now: number,
  rules: MapRefreshRulesDTO,
  rand: () => number = Math.random,
): number {
  const boundary = nextMoscowMidnight(now);
  const jitter = rand() * rules.tick_refresh_jitter_seconds * 1000;
  return (
    boundary - now + rules.tick_refresh_delay_seconds * 1000 + jitter
  );
}

/** Whether a failed request may be retried (≤ max_retries in a row). */
export function shouldRetry(
  consecutiveFailures: number,
  maxRetries: number,
): boolean {
  return consecutiveFailures <= maxRetries;
}

/** True once the last good data is older than `stale_after_seconds`. */
export function isStale(
  lastGoodAt: number | null,
  now: number,
  staleAfterSeconds: number,
): boolean {
  if (lastGoodAt === null) {
    return false;
  }
  return now - lastGoodAt > staleAfterSeconds * 1000;
}

/**
 * ms until the last-good data crosses the stale boundary; null when it
 * is already stale or there is no data. Used to arm the stale-mark timer
 * after retries are exhausted.
 */
export function msUntilStale(
  lastGoodAt: number | null,
  now: number,
  staleAfterSeconds: number,
): number | null {
  if (lastGoodAt === null || isStale(lastGoodAt, now, staleAfterSeconds)) {
    return null;
  }
  return lastGoodAt + staleAfterSeconds * 1000 - now;
}

const moscowTime = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Europe/Moscow',
});

/** «ЧЧ:ММ» in Moscow time for the status line. */
export function formatMoscowTime(timestamp: number): string {
  return moscowTime.format(new Date(timestamp));
}
