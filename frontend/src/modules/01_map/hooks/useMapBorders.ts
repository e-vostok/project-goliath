/**
 * useMapBorders(version) — GET /map/borders/{version} (map2_4).
 *
 * Same contract as useMapGeometry: the body is immutable per version
 * and shared through the session-level cache (lib/sessionCache), and a
 * 404 MAP_VERSION_UNKNOWN re-requests the manifest once and retries
 * with the fresh version. The difference is the failure mode: a
 * missing or broken borders payload is NOT fatal — the map falls back
 * to the legacy per-node strokes. The hook reports `status: 'error'`,
 * logs one console warning per version, and the caller keeps rendering.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError } from '../../../shared/api-client';
import {
  loadBordersCached,
  readBordersCache,
} from '../lib/sessionCache';
import type { MapBordersDTO, MapManifestDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export type BordersState =
  | { status: 'idle' | 'loading'; borders: null }
  | { status: 'error'; borders: null; error: ApiError | Error }
  | { status: 'ready'; borders: MapBordersDTO };

// «One console warning» per failed version — both map consumers share
// the hook, and a second mount must not warn again.
const warnedVersions = new Set<string>();

function warnOnce(version: string, error: unknown): void {
  if (warnedVersions.has(version)) {
    return;
  }
  warnedVersions.add(version);
  console.warn(
    '[01_map] borders layer failed to load; drawing legacy strokes',
    error,
  );
}

export function useMapBorders(
  version: string | null,
  reloadManifest: () => Promise<MapManifestDTO | null>,
): BordersState {
  const { token } = useSession();
  const [state, setState] = useState<BordersState>(() => {
    const cached = version !== null ? readBordersCache(version) : null;
    return cached !== null
      ? { status: 'ready', borders: cached }
      : { status: 'idle', borders: null };
  });
  // Versions already retried once after a manifest reload — the loop guard.
  const retried = useRef(new Set<string>());

  const fetchBorders = useCallback(
    async (v: string) => loadBordersCached(token, v),
    [token],
  );

  useEffect(() => {
    if (version === null) {
      setState({ status: 'idle', borders: null });
      return;
    }
    const cached = readBordersCache(version);
    if (cached !== null) {
      setState({ status: 'ready', borders: cached });
      return;
    }
    const controller = new AbortController();
    setState({ status: 'loading', borders: null });

    fetchBorders(version)
      .then((borders) => {
        if (!controller.signal.aborted) {
          setState({ status: 'ready', borders });
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
            fresh.borders_version !== version &&
            !controller.signal.aborted
          ) {
            // The effect re-runs on the new version — nothing to do here.
            return;
          }
          if (fresh && fresh.borders_version === version) {
            // Manifest revalidation returned the same version but the
            // borders route rejected it — retry the borders once anyway.
            try {
              const borders = await fetchBorders(version);
              if (!controller.signal.aborted) {
                setState({ status: 'ready', borders });
              }
              return;
            } catch {
              /* fall through to the error state below */
            }
          }
        }
        warnOnce(version, error);
        setState({
          status: 'error',
          borders: null,
          error:
            error instanceof Error
              ? error
              : new Error('Неизвестная ошибка загрузки границ'),
        });
      });

    return () => controller.abort();
  }, [version, fetchBorders, reloadManifest]);

  return state;
}
