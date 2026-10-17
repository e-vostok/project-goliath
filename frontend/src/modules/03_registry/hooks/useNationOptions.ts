/**
 * useNationOptions — the nations the Registry already knows, fetched
 * for the `select_or_contains` dropdowns (Spec 3.7).
 *
 * Loads GET /registry/tables/nations lazily — only when the active
 * table actually has a `select_or_contains` column — and keeps the
 * result for the session view. A missing/failed table resolves to
 * `null`; the caller falls back to the nation cells on screen.
 */

import { useEffect, useState } from 'react';

import { registryApi } from '../api';
import { nationNamesOfTable } from '../lib/nationOptions';
import { useSession } from '../../00_core/hooks/useAuth';
import type { RegistryTableDTO } from '../types';

/** The Registry table that lists every nation (configs/03_registry). */
export const NATIONS_TABLE_ID = 'nations';

export function useNationOptions(
  enabled: boolean,
  nationsTable: RegistryTableDTO | null,
): { names: string[] | null } {
  const { token } = useSession();
  const [names, setNames] = useState<string[] | null>(null);
  const wanted = enabled && nationsTable !== null;

  useEffect(() => {
    if (!wanted) {
      return;
    }
    const controller = new AbortController();
    registryApi
      .getRows(token, NATIONS_TABLE_ID, controller.signal)
      .then((dto) => {
        if (!controller.signal.aborted) {
          setNames(nationNamesOfTable(nationsTable, dto));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setNames(null);
        }
      });
    return () => controller.abort();
  }, [token, wanted, nationsTable]);

  return { names };
}
