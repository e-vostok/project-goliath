/**
 * Endpoint helpers for /api/v1/orders/* (Spec 5.1, 5.2) — thin
 * wrappers over the shared api-client. All calls carry the session
 * Bearer token; the order number in the path is a positive integer.
 */

import { apiFetch } from '../../shared/api-client';
import type {
  OrderCreateRequest,
  OrderDetailDTO,
  OrderRulesDTO,
} from './types';

export const ordersApi = {
  /** GET /orders/rules — field limits plus the author's counter. */
  getRules(token: string, signal?: AbortSignal) {
    return apiFetch<OrderRulesDTO>('/orders/rules', { token, signal });
  },

  /** POST /orders — 201 new, 200 idempotent repeat (INV-O9). */
  submitOrder(
    token: string,
    body: OrderCreateRequest,
    signal?: AbortSignal,
  ) {
    return apiFetch<OrderDetailDTO>('/orders', {
      method: 'POST',
      body,
      token,
      signal,
    });
  },

  /** GET /orders/{number} — the public detail; 404 ORDER_NOT_FOUND. */
  getOrder(token: string, number: number, signal?: AbortSignal) {
    return apiFetch<OrderDetailDTO>(
      `/orders/${encodeURIComponent(number)}`,
      { token, signal },
    );
  },
};
