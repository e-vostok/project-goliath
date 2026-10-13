/**
 * Bot status store for module 02_bot (Spec 5.6).
 *
 * `BotStatusProvider` fires GET /bot/status exactly once per app start —
 * it mounts inside SessionProvider, so the first request always runs
 * after authentication succeeded. No refetch loops: consumers only see
 * the fetched state and `update(dto)`, which applies a fresher DTO (the
 * consent/refresh response) through the same normalization.
 *
 * Fail-open (INV-B15): a failed request resolves to 'unavailable' and a
 * missing provider reads as 'unavailable' too — in both cases every bot
 * UI element stays hidden and registration is never blocked.
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { useSession } from '../../00_core/hooks/useAuth';
import {
  fetchBotStatus,
  toBotStatus,
  type BotStatus,
  type BotStatusDTO,
} from '../api';

export interface BotStatusStore {
  state: BotStatus;
  /** Applies a fresher server DTO (POST /bot/consent/refresh answer). */
  update: (dto: BotStatusDTO) => void;
}

/**
 * Hard cap for the ONE app-start status request — apiFetch carries no
 * timeout of its own, and a hung request must not block registration
 * (fail-open, INV-B15). This is a request cap, not a poll interval.
 */
export const BOT_STATUS_TIMEOUT_MS = 8000;

const BotStatusContext = createContext<BotStatusStore | null>(null);

export function BotStatusProvider({ children }: { children: ReactNode }) {
  const { token } = useSession();
  const [state, setState] = useState<BotStatus>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    let settled = false;
    const timeoutId = window.setTimeout(() => {
      settled = true;
      setState({ status: 'unavailable' });
    }, BOT_STATUS_TIMEOUT_MS);
    fetchBotStatus(token, controller.signal)
      .then((dto) => {
        if (!settled && !controller.signal.aborted) {
          setState(toBotStatus(dto));
        }
      })
      .catch(() => {
        if (!settled && !controller.signal.aborted) {
          setState({ status: 'unavailable' });
        }
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [token]);

  const update = useCallback(
    (dto: BotStatusDTO) => setState(toBotStatus(dto)),
    [],
  );

  const value = useMemo<BotStatusStore>(
    () => ({ state, update }),
    [state, update],
  );
  return createElement(BotStatusContext.Provider, { value }, children);
}

/**
 * Current bot status. Outside BotStatusProvider reports 'unavailable':
 * the interface then behaves exactly as if the status request failed.
 */
export function useBotStatus(): BotStatusStore {
  const ctx = useContext(BotStatusContext);
  return (
    ctx ?? { state: { status: 'unavailable' }, update: () => {} }
  );
}
