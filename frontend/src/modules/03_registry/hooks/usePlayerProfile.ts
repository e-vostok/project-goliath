/**
 * usePlayerProfile — GET /registry/players/{number} (Spec 5.6, version
 * 0.10.0 unit 8b): the public card the «Игрок» subscreen shows.
 * `number` is the player's public Registry number (the `p<N>` row
 * key). A 404 / REGISTRY_PLAYER_NOT_FOUND is its own state («Игрок не
 * найден»); any other failure is `error` and «Повторить» refires the
 * request through `reload`. Nothing is cached beyond the mount — the
 * card is re-fetched every time the subscreen opens.
 */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import { registryApi } from '../api';
import type { RegistryPlayerDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type PlayerProfileState =
  | { status: 'loading' }
  | { status: 'ready'; player: RegistryPlayerDTO }
  | { status: 'notfound' }
  | { status: 'error'; error: unknown };

export function usePlayerProfile(number: number): {
  state: PlayerProfileState;
  reload: () => void;
} {
  const { token } = useSession();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PlayerProfileState>({
    status: 'loading',
  });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    registryApi
      .getPlayer(token, number, controller.signal)
      .then((player) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', player });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState(
          error instanceof ApiError &&
            (error.status === 404 ||
              error.code === 'REGISTRY_PLAYER_NOT_FOUND')
            ? { status: 'notfound' }
            : { status: 'error', error },
        );
      });
    return () => controller.abort();
  }, [token, number, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, reload };
}
