/**
 * useOrderDetail — GET /orders/{number} when the detail window opens
 * (Spec 5.4). A 404 `ORDER_NOT_FOUND` is a state, not a crash: the
 * window shows «Приказ не найден».
 */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import { ordersApi } from '../api';
import { OrderErrorCodes, type OrderDetailDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type OrderDetailState =
  | { status: 'loading'; order: null }
  | { status: 'error'; order: null; error: Error; notFound: boolean }
  | { status: 'ready'; order: OrderDetailDTO };

export function useOrderDetail(
  number: number | null,
): OrderDetailState & { reload: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<OrderDetailState>({
    status: 'loading',
    order: null,
  });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (number === null) {
        return;
      }
      try {
        const order = await ordersApi.getOrder(token, number, signal);
        if (signal?.aborted) {
          return;
        }
        setState({ status: 'ready', order });
      } catch (e) {
        if (signal?.aborted) {
          return;
        }
        setState({
          status: 'error',
          order: null,
          error: e instanceof Error ? e : new Error('Неизвестная ошибка'),
          notFound:
            e instanceof ApiError &&
            e.code === OrderErrorCodes.ORDER_NOT_FOUND,
        });
      }
    },
    [number, token],
  );

  useEffect(() => {
    setState({ status: 'loading', order: null });
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const reload = useCallback(() => {
    setState({ status: 'loading', order: null });
    void load();
  }, [load]);

  return { ...state, reload };
}
