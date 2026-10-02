/**
 * useMapManifest — GET /map/manifest with ETag revalidation.
 *
 * The last ETag/body live in the session-level map cache
 * (lib/sessionCache) so the viewing screen and the province picker share
 * one copy. Mount-time revalidation still sends `If-None-Match`; a 304
 * reuses the session copy; a 304 without one triggers one unconditional
 * refetch (decided by lib/cache.decideConditional).
 */

import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import { mapApi } from '../api';
import { decideConditional } from '../lib/cache';
import {
  readManifestCache,
  writeManifestCache,
} from '../lib/sessionCache';
import type { MapManifestDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type ManifestState =
  | { status: 'loading'; manifest: null }
  | { status: 'error'; manifest: null; error: ApiError | Error }
  | { status: 'ready'; manifest: MapManifestDTO };

export function useMapManifest(): ManifestState & {
  /** Force a revalidation; resolves to the fresh manifest (or null). */
  reload: () => Promise<MapManifestDTO | null>;
} {
  const { token } = useSession();
  const [state, setState] = useState<ManifestState>(() => {
    // A warm session cache lets a second consumer render instantly while
    // the conditional request still revalidates in the background.
    const cached = readManifestCache();
    return cached
      ? { status: 'ready', manifest: cached.body }
      : { status: 'loading', manifest: null };
  });

  const load = useCallback(
    async (
      conditional: boolean,
      signal?: AbortSignal,
    ): Promise<MapManifestDTO | null> => {
      const cached = readManifestCache();
      const answer = await mapApi.getManifest(
        token,
        conditional ? cached?.etag : null,
        signal,
      );
      const decision = decideConditional(answer, cached);
      if (decision.action === 'refetch-unconditional') {
        return load(false, signal);
      }
      writeManifestCache(decision.value);
      setState({ status: 'ready', manifest: decision.value.body });
      return decision.value.body;
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(true, controller.signal).catch((error: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      setState((prev) =>
        prev.status === 'ready'
          ? prev // keep the cached manifest — a failed revalidate isn't fatal
          : {
              status: 'error',
              manifest: null,
              error:
                error instanceof Error
                  ? error
                  : new Error('Неизвестная ошибка загрузки манифеста'),
            },
      );
    });
    return () => controller.abort();
  }, [load]);

  const reload = useCallback(async () => {
    try {
      return await load(true);
    } catch {
      return null;
    }
  }, [load]);

  return { ...state, reload };
}
