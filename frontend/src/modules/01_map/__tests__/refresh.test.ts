/**
 * Refresh schedule (Spec 3.10 + the Moscow-midnight deviation): next
 * 00:00 Europe/Moscow, delay + injected jitter, retry counting, the
 * stale flag at exactly stale_after_seconds.
 */

import {
  formatMoscowTime,
  isStale,
  msUntilStale,
  msUntilStateRefresh,
  nextMoscowMidnight,
  shouldRetry,
} from '../lib/refresh';
import type { MapRefreshRulesDTO } from '../types';

const RULES: MapRefreshRulesDTO = {
  tick_refresh_delay_seconds: 5,
  tick_refresh_jitter_seconds: 30,
  retry_delay_seconds: 10,
  max_retries: 3,
  stale_after_seconds: 900,
};

/** 2026-10-02 15:00:00 UTC = 18:00 Moscow. */
const T0 = Date.UTC(2026, 9, 2, 15, 0, 0);

describe('nextMoscowMidnight — UTC+3, fixed offset', () => {
  it('rolls to the next Moscow midnight within a day', () => {
    // 18:00 MSK → next midnight is 2026-10-03 00:00 MSK = 2026-10-02 21:00 UTC
    expect(nextMoscowMidnight(T0)).toBe(Date.UTC(2026, 9, 2, 21, 0, 0));
  });

  it('a moment before midnight lands on that same midnight', () => {
    const before = Date.UTC(2026, 9, 2, 20, 59, 59); // 23:59:59 MSK
    expect(nextMoscowMidnight(before)).toBe(Date.UTC(2026, 9, 2, 21, 0, 0));
  });

  it('exactly at midnight rolls to tomorrow (strictly after)', () => {
    const at = Date.UTC(2026, 9, 2, 21, 0, 0); // 00:00 MSK
    expect(nextMoscowMidnight(at)).toBe(Date.UTC(2026, 9, 3, 21, 0, 0));
  });

  it('crosses a month boundary', () => {
    const endOfOct = Date.UTC(2026, 9, 31, 22, 0, 0); // 2026-11-01 01:00 MSK
    // next 00:00 MSK = 2026-11-01 21:00 UTC
    expect(nextMoscowMidnight(endOfOct)).toBe(Date.UTC(2026, 10, 1, 21, 0, 0));
  });

  it('crosses a year boundary', () => {
    const newYearEve = Date.UTC(2026, 11, 31, 20, 30, 0); // 23:30 MSK
    // next 00:00 MSK = 2026-12-31 21:00 UTC = 2027-01-01 00:00 MSK
    expect(nextMoscowMidnight(newYearEve)).toBe(
      Date.UTC(2026, 11, 31, 21, 0, 0),
    );
  });
});

describe('msUntilStateRefresh — delay + injected jitter', () => {
  it('adds the configured delay and the sampled jitter', () => {
    const rand = () => 0.5; // 15 s of the 30 s jitter range
    const expected =
      nextMoscowMidnight(T0) - T0 + 5_000 + 0.5 * 30_000;
    expect(msUntilStateRefresh(T0, RULES, rand)).toBe(expected);
  });

  it('zero jitter degenerates to boundary + delay', () => {
    const expected = nextMoscowMidnight(T0) - T0 + 5_000;
    expect(msUntilStateRefresh(T0, RULES, () => 0)).toBe(expected);
  });
});

describe('shouldRetry — at most max_retries in a row', () => {
  it('allows exactly max_retries retries', () => {
    expect(shouldRetry(1, 3)).toBe(true);
    expect(shouldRetry(2, 3)).toBe(true);
    expect(shouldRetry(3, 3)).toBe(true);
    expect(shouldRetry(4, 3)).toBe(false);
  });
  it('max_retries 0 forbids retries', () => {
    expect(shouldRetry(1, 0)).toBe(false);
  });
});

describe('isStale / msUntilStale — the «данные устарели» boundary', () => {
  it('is fresh exactly at the boundary, stale one ms later', () => {
    const lastGood = T0;
    const edge = T0 + 900 * 1000;
    expect(isStale(lastGood, edge, 900)).toBe(false);
    expect(isStale(lastGood, edge + 1, 900)).toBe(true);
  });

  it('never reports stale without any data', () => {
    expect(isStale(null, T0 + 10_000_000, 900)).toBe(false);
    expect(msUntilStale(null, T0, 900)).toBeNull();
  });

  it('msUntilStale counts down to the boundary and nulls past it', () => {
    expect(msUntilStale(T0, T0 + 400_000, 900)).toBe(500_000);
    expect(msUntilStale(T0, T0 + 900_001, 900)).toBeNull();
  });
});

describe('formatMoscowTime', () => {
  it('formats HH:MM in Europe/Moscow', () => {
    expect(formatMoscowTime(T0)).toBe('18:00'); // 15:00 UTC = 18:00 MSK
  });
});
