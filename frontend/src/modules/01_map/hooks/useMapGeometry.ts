/**
 * useMapGeometry(version) — GET /map/geometry/{version}.
 *
 * The body is immutable per version and served `Cache-Control: public,
 * max-age=31536000, immutable`, so the browser cache does persistence —
 * the hook just fetches. On 404 MAP_VERSION_UNKNOWN it re-requests the
 * manifest once (via `reloadManifest`) and retries the geometry once
 * with the fresh version; a second failure is an error state.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import { mapApi } from '../api';
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
  const [state, setState] = useState<GeometryState>({
    status: 'idle',
    geometry: null,
  });
  // Manual retry for the error state — re-runs the fetch effect.
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // Versions already retried once after a manifest reload — the loop guard.
  const retried = useRef(new Set<string>());

  const fetchGeometry = useCallback(
    async (v: string, signal?: AbortSignal) =>
      mapApi.getGeometry(token, v, signal),
    [token],
  );

  useEffect(() => {
    if (version === null) {
      setState({ status: 'idle', geometry: null });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading', geometry: null });

    fetchGeometry(version, controller.signal)
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
              const geometry = await fetchGeometry(
                version,
                controller.signal,
              );
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
