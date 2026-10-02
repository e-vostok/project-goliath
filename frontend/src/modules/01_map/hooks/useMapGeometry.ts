/**
 * useMapGeometry(version) — GET /map/geometry/{version}.
 *
 * The body is immutable per version and served `Cache-Control: public,
 * max-age=31536000, immutable`; on top of the browser cache the
 * session-level cache (lib/sessionCache) shares one copy between the
 * viewing screen and the picker, so a same-session open never downloads
 * the ~1.9 MB payload again. On 404 MAP_VERSION_UNKNOWN the hook
 * re-requests the manifest once (via `reloadManifest`) and retries the
 * geometry once with the fresh version; a second failure is an error.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import {
  loadGeometryCached,
  readGeometryCache,
} from '../lib/sessionCache';
import type { MapGeometryDTO, MapManifestDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type GeometryState =
  | { status: 'idle' | 'loading'; geometry: null }
  | { status: 'error'; geometry: null; error: ApiError | Error }
  | { status: 'ready'; geometry: MapGeometryDTO };

export function useMapGeometry(
  version: string | null,
  reloadManifest: () => Promise<MapManifestDTO | null>,
): GeometryState & { retry: () => void } {
  const { token } = useSession();
  const [state, setState] = useState<GeometryState>(() => {
    const cached = version !== null ? readGeometryCache(version) : null;
    return cached !== null
      ? { status: 'ready', geometry: cached }
      : { status: 'idle', geometry: null };
  });
  // Manual retry for the error state — re-runs the fetch effect.
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // Versions already retried once after a manifest reload — the loop guard.
  const retried = useRef(new Set<string>());

  const fetchGeometry = useCallback(
    async (v: string) => loadGeometryCached(token, v),
    [token],
  );

  useEffect(() => {
    if (version === null) {
      setState({ status: 'idle', geometry: null });
      return;
    }
    const cached = readGeometryCache(version);
    if (cached !== null) {
      setState({ status: 'ready', geometry: cached });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading', geometry: null });

    fetchGeometry(version)
      .then((geometry) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', geometry });
        }
      })
      .catch(async (error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        const isVersionUnknown =
          error instanceof ApiError &&
          error.status === 404 &&
          error.code === 'MAP_VERSION_UNKNOWN';
        if (isVersionUnknown && !retried.current.has(version)) {
          retried.current.add(version);
          const fresh = await reloadManifest();
          if (
            fresh &&
            fresh.geometry_version !== version &&
            !controller.signal.aborted
          ) {
            // The effect re-runs on the new version — nothing to do here.
            return;
          }
          if (fresh && fresh.geometry_version === version) {
            // Manifest revalidation returned the same version but the
            // geometry route rejected it — retry the geometry once anyway.
            try {
              const geometry = await fetchGeometry(version);
              if (!controller.signal.aborted) {
                setState({ status: 'ready', geometry });
              }
              return;
            } catch {
              /* fall through to the error state below */
            }
          }
        }
        setState({
          status: 'error',
          geometry: null,
          error:
            error instanceof Error
              ? error
              : new Error('Неизвестная ошибка загрузки геометрии'),
        });
      });

    return () => controller.abort();
  }, [version, attempt, fetchGeometry, reloadManifest]);

  return { ...state, retry };
}
