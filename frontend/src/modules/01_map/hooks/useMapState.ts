/**
 * useMapState — GET /map/state on the Spec 3.10 schedule.
 *
 * Fires on mount (once the refresh rules are known), on returning to the
 * window (visibilitychange / focus), and at the next daily tick boundary
 * + delay + jitter (the boundary is the next Moscow midnight — see
 * lib/refresh.ts for the deviation note). On failure it retries after
 * `retry_delay_seconds`, at most `max_retries` times in a row; when the
 * last good data is older than `stale_after_seconds` the `stale` flag
 * goes up. The last good state is NEVER replaced by an error.
 *
 * `turn` selects a past turn (?turn=) — accepted for the future history
 * slider; the UI for it is a later Issue.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { mapApi } from '../api';
import {
  isStale,
  msUntilStale,
  msUntilStateRefresh,
  shouldRetry,
} from '../lib/refresh';
import type { MapRefreshRulesDTO, MapStateDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export interface MapStateResult {
  status: 'loading' | 'ready' | 'error';
  /** Last good payload — survives failures; null only until first load. */
  state: MapStateDTO | null;
  /** Timestamp (ms) of the last successful fetch — status line uses it. */
  fetchedAt: number | null;
  stale: boolean;
  error: Error | null;
}

export function useMapState(
  rules: MapRefreshRulesDTO | null,
  turn?: number,
  rand: () => number = Math.random,
): MapStateResult {
  const { token } = useSession();
  const [result, setResult] = useState<MapStateResult>({
    status: 'loading',
    state: null,
    fetchedAt: null,
    stale: false,
    error: null,
  });

  const lastGoodAt = useRef<number | null>(null);
  const failures = useRef(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const inFlight = useRef(false);
  const alive = useRef(true);

  const clearTimers = useCallback(() => {
    for (const t of timers.current) {
      clearTimeout(t);
    }
    timers.current = [];
  }, []);

  const later = useCallback((fn: () => void, ms: number) => {
    timers.current.push(setTimeout(fn, ms));
  }, []);

  const attempt = useCallback(async () => {
    if (rules === null || inFlight.current) {
      return;
    }
    inFlight.current = true;
    try {
      const state = await mapApi.getState(token, turn);
      const now = Date.now();
      lastGoodAt.current = now;
      failures.current = 0;
      if (!alive.current) {
        return;
      }
      setResult({
        status: 'ready',
        state,
        fetchedAt: now,
        stale: false,
        error: null,
      });
      // Next poll: the following daily tick boundary (Spec 3.10).
      const delay = msUntilStateRefresh(now, rules, rand);
      later(() => {
        void attempt();
      }, delay);
    } catch (error) {
      const now = Date.now();
      failures.current += 1;
      const err = error instanceof Error ? error : new Error(String(error));
      const staleNow = isStale(
        lastGoodAt.current,
        now,
        rules.stale_after_seconds,
      );
      if (!alive.current) {
        return;
      }
      setResult((prev) => ({
        status: prev.state === null ? 'error' : prev.status,
        state: prev.state,
        fetchedAt: prev.fetchedAt,
        stale: prev.stale || staleNow,
        error: err,
      }));

      if (shouldRetry(failures.current, rules.max_retries)) {
        later(() => {
          void attempt();
        }, rules.retry_delay_seconds * 1000);
      } else {
        // Retries exhausted: arm the stale-mark timer if the data will
        // cross the boundary later, and keep the regular tick schedule.
        const staleIn = msUntilStale(
          lastGoodAt.current,
          now,
          rules.stale_after_seconds,
        );
        if (staleIn !== null) {
          later(() => {
            setResult((prev) => ({ ...prev, stale: true }));
          }, staleIn);
        }
        const delay = msUntilStateRefresh(now, rules, rand);
        later(() => {
          failures.current = 0;
          void attempt();
        }, delay);
      }
    } finally {
      inFlight.current = false;
    }
  }, [rules, token, turn, rand, later]);

  useEffect(() => {
    if (rules === null) {
      return;
    }
    alive.current = true;
    void attempt();

    const onVisible = () => {
      if (document.visibilityState === 'visible') {
        failures.current = 0;
        void attempt();
      }
    };
    const onFocus = () => {
      failures.current = 0;
      void attempt();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);
    return () => {
      alive.current = false;
      clearTimers();
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
    };
  }, [rules, attempt, clearTimers]);

  return result;
}
