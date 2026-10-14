/**
 * useRegistryRows — GET /registry/tables/{tableId}.
 *
 * Fires on tab open (tableId change) and on «Обновить» (Spec 5.5 /
 * Bible 2.6). A failed reload keeps the previously shown rows and
 * surfaces the error; a sequence counter drops stale responses.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { registryApi } from '../api';
import type { RegistryRowsDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export interface RegistryRowsState {
  status: 'loading' | 'ready' | 'error';
  /** Last successfully loaded payload — kept after a failed reload. */
  data: RegistryRowsDTO | null;
  error: Error | null;
  /** True while «Обновить» is in flight with data on screen. */
  refreshing: boolean;
}

function toError(e: unknown): Error {
  return e instanceof Error
    ? e
    : new Error('Erro desconhecido ao carregar a tabela');
}

export function useRegistryRows(
  tableId: string | null,
): RegistryRowsState & { reload: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<RegistryRowsState>({
    status: 'loading',
    data: null,
    error: null,
    refreshing: false,
  });
  const seq = useRef(0);

  const fetchRows = useCallback(
    async (keepData: boolean, signal?: AbortSignal) => {
      if (!tableId) {
        return;
      }
      const mySeq = ++seq.current;
      if (!keepData) {
        setState({
          status: 'loading',
          data: null,
          error: null,
          refreshing: false,
        });
      } else {
        setState((prev) => ({ ...prev, error: null, refreshing: true }));
      }
      try {
        const data = await registryApi.getRows(token, tableId, signal);
        if (mySeq !== seq.current || signal?.aborted) {
          return;
        }
        setState({
          status: 'ready',
          data,
          error: null,
          refreshing: false,
        });
      } catch (e) {
        if (mySeq !== seq.current || signal?.aborted) {
          return;
        }
        setState((prev) => ({
          status: 'error',
          data: prev.data,
          error: toError(e),
          refreshing: false,
        }));
      }
    },
    [token, tableId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void fetchRows(false, controller.signal);
    return () => controller.abort();
  }, [fetchRows]);

  const reload = useCallback(() => {
    void fetchRows(true);
  }, [fetchRows]);

  return { ...state, reload };
}
