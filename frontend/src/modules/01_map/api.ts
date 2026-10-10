/**
 * Endpoint helpers for /api/v1/map/* (Spec Part 5) — thin wrappers over
 * the shared api-client. All calls carry the session Bearer token; the
 * map works for players without a nation, so no nation checks here.
 */

import {
  apiFetch,
  apiFetchConditional,
  type ConditionalResult,
} from '../../shared/api-client';
import type {
  MapBordersDTO,
  MapGeometryDTO,
  MapManifestDTO,
  MapStateDTO,
  StartingGroupCheckDTO,
} from './types';

export const mapApi = {
  /** GET /map/manifest — conditional when `etag` is given (304 reuse). */
  getManifest(
    token: string,
    etag?: string | null,
    signal?: AbortSignal,
  ): Promise<ConditionalResult<MapManifestDTO>> {
    return apiFetchConditional<MapManifestDTO>('/map/manifest', {
      token,
      signal,
      ifNoneMatch: etag ?? undefined,
    });
  },

  /** GET /map/geometry/{version} — immutable; 404 MAP_VERSION_UNKNOWN. */
  getGeometry(token: string, version: string, signal?: AbortSignal) {
    return apiFetch<MapGeometryDTO>(`/map/geometry/${version}`, {
      token,
      signal,
    });
  },

  /** GET /map/borders/{version} — immutable; 404 MAP_VERSION_UNKNOWN. */
  getBorders(token: string, version: string, signal?: AbortSignal) {
    return apiFetch<MapBordersDTO>(`/map/borders/${version}`, {
      token,
      signal,
    });
  },

  /** GET /map/state — current turn, or a past turn via `?turn=`. */
  getState(token: string, turn?: number, signal?: AbortSignal) {
    const query = turn !== undefined ? `?turn=${turn}` : '';
    return apiFetch<MapStateDTO>(`/map/state${query}`, { token, signal });
  },

  /**
   * POST /map/starting-group/check — server-side connectivity of a
   * would-be starting group (Spec Part 5); the picker calls it before
   * closing. Unknown ids -> PROVINCE_NOT_FOUND, sea -> PROVINCE_NOT_LAND.
   */
  checkStartingGroup(
    token: string,
    provinceIds: number[],
    signal?: AbortSignal,
  ) {
    return apiFetch<StartingGroupCheckDTO>('/map/starting-group/check', {
      method: 'POST',
      token,
      body: { province_ids: provinceIds },
      signal,
    });
  },
};
