/**
 * useAssignedOrders — GET /orders/assigned for the «Ожидают вердикт»
 * list (Spec 5.4). Loads when the block mounts and on `refresh()` —
 * there is no polling; `refreshKey` is bumped by the provider when a
 * verdict is written or rejected, because the judge's queue changed
 * under it. A failed refresh keeps the last loaded list: the block
 * shows «Не удалось загрузить» with «Повторить» over it.
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
