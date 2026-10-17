/**
 * Endpoint helpers for /api/v1/registry/* (Spec 5.1, 5.2) — thin
 * wrappers over the shared api-client. All calls carry the session
 * Bearer token; the Registry works for players without a nation.
 */

import { apiFetch } from '../../shared/api-client';
import type { RegistryRowsDTO, RegistryTablesDTO } from './types';

export const registryApi = {
  /** GET /registry/tables — layout + description of every table. */
  getTables(token: string, signal?: AbortSignal) {
    return apiFetch<RegistryTablesDTO>('/registry/tables', { token, signal });
  },

  /** GET /registry/tables/{tableId} — all rows of a table (Spec D6). */
  getRows(token: string, tableId: string, signal?: AbortSignal) {
    return apiFetch<RegistryRowsDTO>(
      `/registry/tables/${encodeURIComponent(tableId)}`,
      { token, signal },
    );
  },
};
