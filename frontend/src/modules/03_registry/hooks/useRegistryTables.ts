/**
 * useRegistryTables — GET /registry/tables once when the panel opens
 * (Spec 5.5: the table descriptions are requested a single time).
 */

import { useCallback, useEffect, useState } from 'react';

import { registryApi } from '../api';
import type { RegistryTablesDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export interface RegistryTablesState {
  status: 'loading' | 'ready' | 'error';
  data: RegistryTablesDTO | null;
  error: Error | null;
}

export function useRegistryTables(): RegistryTablesState & {
  reload: () => void;
} {
  const { token } = useSession();
  const [state, setState] = useState<RegistryTablesState>({
    status: 'loading',
    data: null,
    error: null,
  });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await registryApi.getTables(token, signal);
        if (signal?.aborted) {
          return;
        }
        setState({ status: 'ready', data, error: null });
      } catch (e) {
        if (signal?.aborted) {
          return;
        }
        setState({
          status: 'error',
          data: null,
          error:
            e instanceof Error
              ? e
              : new Error('Erro desconhecido ao carregar as tabelas'),
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

  const reload = useCallback(() => {
    setState({ status: 'loading', data: null, error: null });
    void load();
  }, [load]);

  return { ...state, reload };
}
