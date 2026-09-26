/**
 * Province list for module 00_core (GET /provinces).
 *
 * Used by the create-nation form to hint which province IDs are free.
 * Pass `{ freeOnly: true }` for the unowned subset, or `ids` to look up
 * specific provinces.
 */

import { useEffect, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type { ProvinceDTO } from '../../../shared/types';
import { useSession } from './useAuth';

export interface ProvincesFilter {
  ids?: number[];
  freeOnly?: boolean;
}

export type ProvincesState =
  | { status: 'loading'; provinces: [] }
  | { status: 'error'; provinces: []; error: ApiError | Error }
  | { status: 'ready'; provinces: ProvinceDTO[] };

export function useProvinces(filter: ProvincesFilter = {}): ProvincesState {
  const { token } = useSession();
  const [state, setState] = useState<ProvincesState>({
    status: 'loading',
    provinces: [],
  });

  const idsKey = (filter.ids ?? []).join(',');
  const freeOnly = filter.freeOnly ?? false;

  useEffect(() => {
    const controller = new AbortController();
    const ids = idsKey ? idsKey.split(',').map(Number) : undefined;

    api
      .getProvinces(token, { ids, freeOnly }, controller.signal)
      .then((provinces) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', provinces });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: 'error',
          provinces: [],
          error:
            error instanceof Error ? error : new Error('Unknown error'),
        });
      });

    return () => controller.abort();
  }, [token, idsKey, freeOnly]);

  return state;
}
