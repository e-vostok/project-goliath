/**
 * Session-level cache of the map payloads (Spec Part 5: the ~1.9 MB
 * geometry must be downloaded at most once per session).
 *
 * The map screen and the province picker are separate component trees;
 * hook-local refs would refetch the geometry each time the picker opens.
 * This module holds the payloads for the page session instead:
 *
 * - the manifest as a { etag, body } pair — mount-time revalidation
 *   still runs (If-None-Match -> 304 reuses this body);
 * - geometry bodies keyed by their immutable version, plus an in-flight
 *   dedup so two consumers mounting together fire one request.
 *
 * `clearMapSessionCache()` exists for tests — module state survives
 * between tests otherwise.
 */

import type { CachedBody } from './cache';
import { mapApi } from '../api';
import type {
  MapBordersDTO,
  MapGeometryDTO,
  MapManifestDTO,
} from '../types';

let manifestCache: CachedBody<MapManifestDTO> | null = null;
const geometryCache = new Map<string, MapGeometryDTO>();
const geometryInflight = new Map<string, Promise<MapGeometryDTO>>();
const bordersCache = new Map<string, MapBordersDTO>();
const bordersInflight = new Map<string, Promise<MapBordersDTO>>();

export function readManifestCache(): CachedBody<MapManifestDTO> | null {
  return manifestCache;
}

export function writeManifestCache(
  value: CachedBody<MapManifestDTO>,
): void {
  manifestCache = value;
}

export function readGeometryCache(version: string): MapGeometryDTO | null {
  return geometryCache.get(version) ?? null;
}

/**
 * Fetch a geometry version once per session: a completed body is served
 * from memory, a concurrent call joins the in-flight request, and only
 * the first caller reaches the network. A failed request is forgotten —
 * the next caller retries normally.
 */
export function loadGeometryCached(
  token: string,
  version: string,
): Promise<MapGeometryDTO> {
  const hit = geometryCache.get(version);
  if (hit) {
    return Promise.resolve(hit);
  }
  const inflight = geometryInflight.get(version);
  if (inflight) {
    return inflight;
  }
  const request = mapApi.getGeometry(token, version).then(
    (geometry) => {
      geometryCache.set(version, geometry);
      geometryInflight.delete(version);
      return geometry;
    },
    (error: unknown) => {
      geometryInflight.delete(version);
      throw error instanceof Error ? error : new Error(String(error));
    },
  );
  geometryInflight.set(version, request);
  return request;
}

export function readBordersCache(version: string): MapBordersDTO | null {
  return bordersCache.get(version) ?? null;
}

/**
 * Fetch a borders version once per session — same once-per-session
 * contract as `loadGeometryCached` (map2_4: the payload is cached like
 * the geometry).
 */
export function loadBordersCached(
  token: string,
  version: string,
): Promise<MapBordersDTO> {
  const hit = bordersCache.get(version);
  if (hit) {
    return Promise.resolve(hit);
  }
  const inflight = bordersInflight.get(version);
  if (inflight) {
    return inflight;
  }
  const request = mapApi.getBorders(token, version).then(
    (borders) => {
      bordersCache.set(version, borders);
      bordersInflight.delete(version);
      return borders;
    },
    (error: unknown) => {
      bordersInflight.delete(version);
      throw error instanceof Error ? error : new Error(String(error));
    },
  );
  bordersInflight.set(version, request);
  return request;
}

/** Forget everything — called by test stubs to isolate test cases. */
export function clearMapSessionCache(): void {
  manifestCache = null;
  geometryCache.clear();
  geometryInflight.clear();
  bordersCache.clear();
  bordersInflight.clear();
}
