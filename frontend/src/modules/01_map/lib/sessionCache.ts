/**
 * Session-level cache of the map payloads (Spec Part 5: the ~1.9 MB
 * geometry must be downloaded at most once per session).
 *
 * The map screen and the province picker are separate component trees;
 * hook-local refs would refetch the geometry each time the picker opens.
 * This module holds the payloads for the page session instead:
 *
 * - the manifest as a { etag, body } pair — mount-time revalidation
 *   still runs (If-None-Match -> 304 reuses this body). The pair is also
 *   mirrored to localStorage (load-speed unit 10) under a key carrying
 *   the app version, so a cold start revalidates against the stored
 *   ETag instead of re-downloading ~103 KB; a new build ignores — and
 *   replaces — the old copy;
 * - geometry bodies keyed by their immutable version, plus an in-flight
 *   dedup so two consumers mounting together fire one request.
 *
 * `clearMapSessionCache()` exists for tests — module state survives
 * between tests otherwise.
 */

import { version as APP_VERSION } from '../../../../package.json';

import type { CachedBody } from './cache';
import { startReliefDownload } from './relief';
import { mapApi } from '../api';
import type {
  MapBordersDTO,
  MapGeometryDTO,
  MapManifestDTO,
} from '../types';

/**
 * The stored manifest copy: `{ v, etag, body }` under a key that carries
 * the app version, so every build revalidates fresh instead of trusting
 * a previous deploy's data. `v` is the envelope schema — bump it if the
 * stored shape changes.
 */
export const MANIFEST_STORAGE_KEY = `pax.map.manifest:${APP_VERSION}`;
const MANIFEST_STORAGE_SCHEMA = 1;
/** The body is ~0.8 MB — anything much bigger is corrupt; ignore it. */
const MANIFEST_STORAGE_MAX_CHARS = 4_000_000;
const MANIFEST_STORAGE_PREFIX = 'pax.map.manifest:';

function readStoredManifest(): CachedBody<MapManifestDTO> | null {
  try {
    const raw = window.localStorage.getItem(MANIFEST_STORAGE_KEY);
    if (raw === null || raw.length > MANIFEST_STORAGE_MAX_CHARS) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object') {
      return null;
    }
    const entry = parsed as { v?: unknown; etag?: unknown; body?: unknown };
    if (
      entry.v !== MANIFEST_STORAGE_SCHEMA ||
      entry.body === null ||
      typeof entry.body !== 'object'
    ) {
      return null;
    }
    return {
      etag: typeof entry.etag === 'string' ? entry.etag : null,
      body: entry.body as MapManifestDTO,
    };
  } catch {
    // Corrupt JSON or unavailable storage — treated as no stored copy.
    return null;
  }
}

function writeStoredManifest(value: CachedBody<MapManifestDTO>): void {
  try {
    window.localStorage.setItem(
      MANIFEST_STORAGE_KEY,
      JSON.stringify({
        v: MANIFEST_STORAGE_SCHEMA,
        etag: value.etag,
        body: value.body,
      }),
    );
    // One stored copy per app build — older builds' entries would
    // otherwise accumulate ~0.8 MB each.
    for (const key of Object.keys(window.localStorage)) {
      if (
        key.startsWith(MANIFEST_STORAGE_PREFIX) &&
        key !== MANIFEST_STORAGE_KEY
      ) {
        window.localStorage.removeItem(key);
      }
    }
  } catch {
    // Quota or privacy mode — the in-memory session cache still works.
  }
}

let manifestCache: CachedBody<MapManifestDTO> | null = null;
let manifestSeeded = false;
const geometryCache = new Map<string, MapGeometryDTO>();
const geometryInflight = new Map<string, Promise<MapGeometryDTO>>();
const bordersCache = new Map<string, MapBordersDTO>();
const bordersInflight = new Map<string, Promise<MapBordersDTO>>();

export function readManifestCache(): CachedBody<MapManifestDTO> | null {
  if (!manifestSeeded) {
    // First read of the page session seeds from the stored copy so the
    // mount-time conditional request can already send its ETag.
    manifestSeeded = true;
    manifestCache = readStoredManifest();
  }
  return manifestCache;
}

export function writeManifestCache(
  value: CachedBody<MapManifestDTO>,
): void {
  if (value === manifestCache) {
    // A 304 revalidation writes back the very same object — nothing new
    // to store (and ~0.8 MB of JSON.stringify saved).
    return;
  }
  manifestCache = value;
  writeStoredManifest(value);
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
  // A map is being assembled (viewing screen or picker): start the two
  // relief rasters now — they used to wait for MapView's mount after
  // the geometry arrived (load-speed unit 10). Same `rules.relief`
  // switch useRelief reads; the download itself dedupes to one request
  // per file.
  if (manifestCache?.body.rules.relief?.enabled === true) {
    void startReliefDownload();
  }
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
  manifestSeeded = false;
  try {
    window.localStorage.removeItem(MANIFEST_STORAGE_KEY);
  } catch {
    // Storage unavailable — nothing to forget there anyway.
  }
  geometryCache.clear();
  geometryInflight.clear();
  bordersCache.clear();
  bordersInflight.clear();
}
