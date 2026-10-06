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

const BotStatusContext = createContext<BotStatusStore | null>(null);

export function BotStatusProvider({ children }: { children: ReactNode }) {
  const { token } = useSession();
  const [state, setState] = useState<BotStatus>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    fetchBotStatus(token, controller.signal)
      .then((dto) => {
        if (!controller.signal.aborted) {
          setState(toBotStatus(dto));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ status: 'unavailable' });
        }
      });
    return () => controller.abort();
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
