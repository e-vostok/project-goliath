/**
 * useConsentPolling — shared "ждём подтверждения от ВК" loop used by the
 * consent gate and the nation-screen row (Spec 5.6).
 *
 * `start()` begins polling POST /bot/consent/refresh every
 * `intervalSeconds`; the loop stops on `consent = ALLOWED` (→ `onAllowed`)
 * or after `timeoutSeconds` (→ state 'timed_out'). Answers with
 * `throttled = true` and network/API errors are ignored — polling simply
 * continues until the deadline. A 409 BOT_DISABLED ends polling and
 * reports 'disabled'. One extra check fires when the tab becomes
 * visible/focused again while polling is active. All timers are cleared
 * on unmount; nothing runs before `start()`.
 *
 * `checkOnce()` performs a single refresh — the «Проверить ещё раз»
 * button after a timeout.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '../../00_core/hooks/useAuth';
import {
  isBotDisabledError,
  refreshConsent,
  type BotStatusDTO,
} from '../api';

export type ConsentPollingState =
  | 'idle'
  | 'polling'
  | 'timed_out'
  | 'disabled';

export interface ConsentPollingOptions {
  intervalSeconds: number;
  timeoutSeconds: number;
  /** Called with the fresh DTO as soon as consent becomes ALLOWED. */
  onAllowed: (dto: BotStatusDTO) => void;
  /** Called when a refresh answers 409 BOT_DISABLED. */
  onDisabled?: () => void;
}

export interface ConsentPolling {
  state: ConsentPollingState;
  start: () => void;
  checkOnce: () => void;
}

export function useConsentPolling({
  intervalSeconds,
  timeoutSeconds,
  onAllowed,
  onDisabled,
}: ConsentPollingOptions): ConsentPolling {
  const { token } = useSession();
  const [state, setState] = useState<ConsentPollingState>('idle');

  const aliveRef = useRef(true);
  const pollingRef = useRef(false);
  const intervalTimerRef = useRef<number | null>(null);
  const timeoutTimerRef = useRef<number | null>(null);
  const extraCheckInFlightRef = useRef(false);
  const callbacksRef = useRef({ onAllowed, onDisabled });
  callbacksRef.current = { onAllowed, onDisabled };

  const clearTimers = useCallback(() => {
    if (intervalTimerRef.current !== null) {
      clearTimeout(intervalTimerRef.current);
      intervalTimerRef.current = null;
    }
    if (timeoutTimerRef.current !== null) {
      clearTimeout(timeoutTimerRef.current);
      timeoutTimerRef.current = null;
    }
  }, []);

  const stop = useCallback(() => {
    pollingRef.current = false;
    clearTimers();
  }, [clearTimers]);

  /**
   * One POST /bot/consent/refresh. Terminal outcomes (ALLOWED, bot
   * disabled) are applied even if the interval loop already stopped —
   * an ALLOWED that lands after the timeout still opens the form.
   * Everything else is ignored by design.
   */
  const runCheck = useCallback(async () => {
    try {
      const dto = await refreshConsent(token);
      if (!aliveRef.current) {
        return;
      }
      if (dto.consent === 'ALLOWED') {
        stop();
        setState('idle');
        callbacksRef.current.onAllowed(dto);
      }
    } catch (error) {
      if (!aliveRef.current) {
        return;
      }
      if (isBotDisabledError(error)) {
        stop();
        setState('disabled');
        callbacksRef.current.onDisabled?.();
      }
      // throttled answers land in the try-branch above; every other
      // failure is ignored — polling continues until the deadline.
    }
  }, [token, stop]);

  const start = useCallback(() => {
    stop();
    pollingRef.current = true;
    setState('polling');

    const tick = () => {
      if (!pollingRef.current) {
        return;
      }
      void runCheck().then(() => {
        if (pollingRef.current) {
          intervalTimerRef.current = window.setTimeout(
            tick,
            intervalSeconds * 1000,
          );
        }
      });
    };
    intervalTimerRef.current = window.setTimeout(
      tick,
      intervalSeconds * 1000,
    );
    timeoutTimerRef.current = window.setTimeout(() => {
      stop();
      setState('timed_out');
    }, timeoutSeconds * 1000);
  }, [intervalSeconds, timeoutSeconds, runCheck, stop]);

  const checkOnce = useCallback(() => {
    void runCheck();
  }, [runCheck]);

  // One extra refresh when the user returns to the tab mid-polling.
  useEffect(() => {
    const onReturn = () => {
      if (!pollingRef.current || extraCheckInFlightRef.current) {
        return;
      }
      extraCheckInFlightRef.current = true;
      void runCheck().finally(() => {
        extraCheckInFlightRef.current = false;
      });
    };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        onReturn();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onReturn);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('focus', onReturn);
    };
  }, [runCheck]);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      stop();
    };
  }, [stop]);

  return { state, start, checkOnce };
}
