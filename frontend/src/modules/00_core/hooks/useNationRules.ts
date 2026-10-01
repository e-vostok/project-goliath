/**
 * Nation creation/update limits for module 00_core (GET /nations/rules).
 *
 * The backend's CoreConfig is the source of truth for lengths, province
 * bounds and allowed history-link hosts; components use these rules only
 * for hints (`FormItem.bottom`, `maxLength`) and for gating the submit
 * button. A failed rules request must never block the forms — callers
 * degrade to "non-empty" checks when `status` is 'error'.
 */

import { useEffect, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type { NationRulesDTO } from '../../../shared/types';
import { useSession } from './useAuth';

export type NationRulesState =
  | { status: 'loading'; rules: null }
  | { status: 'error'; rules: null; error: ApiError | Error }
  | { status: 'ready'; rules: NationRulesDTO };

export function useNationRules(): NationRulesState {
  const { token } = useSession();
  const [state, setState] = useState<NationRulesState>({
    status: 'loading',
    rules: null,
  });

  useEffect(() => {
    const controller = new AbortController();

    api
      .getNationRules(token, controller.signal)
      .then((rules) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', rules });
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: 'error',
          rules: null,
          error:
            error instanceof Error ? error : new Error('Неизвестная ошибка'),
        });
      });

    return () => controller.abort();
  }, [token]);

  return state;
}
