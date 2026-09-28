/**
 * The authenticated player's nation, fetched via GET /nations/me.
 *
 * `status` lifecycle: 'loading' → 'ready' (nation may be null — the player
 * simply has none yet) or 'error'. A 404/NATION_NOT_FOUND response is the
 * normal "no nation" signal, not an error.
 */

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { ErrorCodes, type NationDTO } from '../../../shared/types';
import { useSession } from './useAuth';

export type NationState =
  | { status: 'loading'; nation: null }
  | { status: 'error'; nation: null; error: ApiError | Error }
  | { status: 'ready'; nation: NationDTO | null };

export function useNation(): NationState & { refresh: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<NationState>({
    status: 'loading',
    nation: null,
  });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const nation = await api.getMyNation(token, signal);
        setState({ status: 'ready', nation });
      } catch (error) {
        if (signal?.aborted) {
          return;
        }
        if (
          error instanceof ApiError &&
          (error.status === 404 || error.code === ErrorCodes.NATION_NOT_FOUND)
        ) {
          setState({ status: 'ready', nation: null });
          return;
        }
        setState({
          status: 'error',
          nation: null,
          error:
            error instanceof Error ? error : new Error('Неизвестная ошибка'),
        });
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return { ...state, refresh };
}
