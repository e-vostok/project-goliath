/**
 * useAssignedOrders — GET /orders/assigned for the «Приказы других
 * игроков» badge (Spec 5.4, unit 7b — the endpoint is unpaginated and
 * returns the judge's whole queue, so the badge counts `items.length`).
 * Loads on mount and whenever `refreshKey` changes — the provider
 * bumps it when a verdict is written or rejected, because the judge's
 * queue changed under it. A failed refresh keeps the last loaded list
 * (the badge simply keeps showing the previous count — or none).
 */

import { useCallback, useEffect, useState } from 'react';

import { ordersApi } from '../api';
import type { AssignedOrderDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type AssignedOrdersState = {
  /** The last loaded queue — survives a failed refresh. */
  items: AssignedOrderDTO[];
  refresh: () => void;
} & (
  | { status: 'loading'; error: null }
  | { status: 'error'; error: Error }
  | { status: 'ready'; error: null }
);

export function useAssignedOrders(refreshKey = 0): AssignedOrdersState {
  const { token } = useSession();
  const [state, setState] = useState<
    {
      items: AssignedOrderDTO[];
    } & (
      | { status: 'loading'; error: null }
      | { status: 'error'; error: Error }
      | { status: 'ready'; error: null }
    )
  >({ status: 'loading', items: [], error: null });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setState((s) => ({ ...s, status: 'loading', error: null }));
      try {
        const dto = await ordersApi.getAssigned(token, signal);
        if (signal?.aborted) {
          return;
        }
        setState({ status: 'ready', items: dto.items, error: null });
      } catch (e) {
        if (signal?.aborted) {
          return;
        }
        setState((s) => ({
          status: 'error',
          items: s.items,
          error: e instanceof Error ? e : new Error('Неизвестная ошибка'),
        }));
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshKey]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return { ...state, refresh };
}
