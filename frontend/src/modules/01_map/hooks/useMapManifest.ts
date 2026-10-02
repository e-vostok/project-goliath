/**
 * useMapManifest — GET /map/manifest with ETag revalidation.
 *
 * Keeps the last ETag and body in memory (a ref — the manifest is large
 * and immutable per version). Revalidation sends `If-None-Match`; a 304
 * reuses the memory copy; a 304 without a memory copy triggers one
 * unconditional refetch (decided by lib/cache.decideConditional).
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import { mapApi } from '../api';
import {
  decideConditional,
  type CachedBody,
} from '../lib/cache';
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
  const cache = useRef<CachedBody<MapManifestDTO> | null>(null);
  const [state, setState] = useState<ManifestState>({
    status: 'loading',
    manifest: null,
  });

  const load = useCallback(
    async (
      conditional: boolean,
      signal?: AbortSignal,
    ): Promise<MapManifestDTO | null> => {
      const answer = await mapApi.getManifest(
        token,
        conditional ? cache.current?.etag : null,
        signal,
      );
      const decision = decideConditional(answer, cache.current);
      if (decision.action === 'refetch-unconditional') {
        return load(false, signal);
      }
      cache.current = decision.value;
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
      setState({
        status: 'error',
        manifest: null,
        error:
          error instanceof Error
            ? error
            : new Error('Неизвестная ошибка загрузки манифеста'),
      });
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
