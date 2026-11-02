/**
 * The authenticated player's live application («анкета»), fetched via
 * GET /applications/me.
 *
 * `status` lifecycle: 'loading' → 'ready' (application may be null —
 * the player simply has none) or 'error'. A 404/APPLICATION_NOT_FOUND
 * response is the normal "no application" signal, not an error; only
 * DRAFT and PENDING come back — an accepted application turns into a
 * nation and the GET answers 404.
 *
 * `onGone` fires when a refresh finds the application that used to be
 * there gone: the shell then refetches the nation, so an accepted
 * player's «Штаб» appears without a reload.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { ErrorCodes, type ApplicationDTO } from '../../../shared/types';
import { useSession } from './useAuth';

export type ApplicationState =
  | { status: 'loading'; application: null }
  | { status: 'error'; application: null; error: ApiError | Error }
  | { status: 'ready'; application: ApplicationDTO | null };

export function useApplication(
  onGone?: () => void,
): ApplicationState & { refresh: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<ApplicationState>({
    status: 'loading',
    application: null,
  });
  const hadApplication = useRef(false);
  const onGoneRef = useRef(onGone);
  onGoneRef.current = onGone;

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const application = await api.getMyApplication(token, signal);
        hadApplication.current = true;
        setState({ status: 'ready', application });
      } catch (error) {
        if (signal?.aborted) {
          return;
        }
        if (
          error instanceof ApiError &&
          (error.status === 404 ||
            error.code === ErrorCodes.APPLICATION_NOT_FOUND)
        ) {
          if (hadApplication.current) {
            hadApplication.current = false;
            // The live application vanished — most likely accepted.
            onGoneRef.current?.();
          }
          setState({ status: 'ready', application: null });
          return;
        }
        setState({
          status: 'error',
          application: null,
          error:
            error instanceof Error ? error : new Error('Неизвестная ошибка'),
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

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return { ...state, refresh };
}
