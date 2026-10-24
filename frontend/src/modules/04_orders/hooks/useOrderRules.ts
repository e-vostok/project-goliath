/**
 * useOrderRules — GET /orders/rules when the composer mounts and on
 * `reload` (Spec 5.4: the limits and the author's unresolved counter
 * come from the server — the client never hardcodes them). A failed
 * request never blocks the form: callers degrade to no counters and
 * no client-side gating, the server stays the validator.
 * `refreshKey` refetches on change — the «Мои приказы» badge passes
 * the provider's `ordersRefreshKey` so its count follows a submit.
 */

import { useCallback, useEffect, useState } from 'react';

import { ordersApi } from '../api';
import type { OrderRulesDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type OrderRulesState =
  | { status: 'loading'; rules: null }
  | { status: 'error'; rules: null; error: Error }
  | { status: 'ready'; rules: OrderRulesDTO };

export function useOrderRules(
  refreshKey = 0,
): OrderRulesState & { reload: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<OrderRulesState>({
    status: 'loading',
    rules: null,
  });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const rules = await ordersApi.getRules(token, signal);
        if (signal?.aborted) {
          return;
        }
        setState({ status: 'ready', rules });
      } catch (e) {
        if (signal?.aborted) {
          return;
        }
        setState({
          status: 'error',
          rules: null,
          error: e instanceof Error ? e : new Error('Неизвестная ошибка'),
        });
      }
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshKey]);

  const reload = useCallback(() => {
    setState({ status: 'loading', rules: null });
    void load();
  }, [load]);

  return { ...state, reload };
}
