/**
 * Auth gate for module 00_core.
 *
 * On mount the Mini App reads its own launch URL (`window.location.search` —
 * the correct source per Spec Part 5, this is not an API call) and exchanges
 * it for a short-lived Bearer JWT via POST /api/v1/auth/vk.
 *
 * The token is held in React state/context for the session only — it is
 * deliberately NOT persisted to localStorage, because VK Mini Apps relaunch
 * with fresh launch params every time and re-authentication on each load is
 * the correct behavior.
 */

import {
  createContext,
  createElement,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type { PlayerDTO } from '../../../shared/types';

export type AuthState =
  | { status: 'loading' }
  | { status: 'error'; error: ApiError | Error }
  | { status: 'authenticated'; token: string; player: PlayerDTO };

/**
 * Runs the VK launch-params → JWT exchange once on mount.
 * Re-running is a full page reload in a Mini App, so no retry loop here.
 */
export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();

    api
      .authVk(window.location.search, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setState({
            status: 'authenticated',
            token: response.access_token,
            player: response.player,
          });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: 'error',
          error:
            error instanceof Error
              ? error
              : new Error('Неизвестная ошибка авторизации'),
        });
      });

    return () => controller.abort();
  }, []);

  return state;
}

export interface Session {
  token: string;
  player: PlayerDTO;
}

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({
  session,
  children,
}: {
  session: Session;
  children: ReactNode;
}) {
  // createElement, not JSX — this file is intentionally `.ts`, not `.tsx`.
  return createElement(SessionContext.Provider, { value: session }, children);
}

/** Session token + player for authenticated subtrees. Throws outside the gate. */
export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) {
    throw new Error('useSession must be used inside SessionProvider');
  }
  return session;
}
