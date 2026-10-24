import { useEffect, useState } from 'react';

import manifest from '../relief/manifest.json';
import type { MapReliefRulesDTO } from '../types';

/**
 * One baked relief layer from `tools/map_pipeline/build_relief.py`:
 * a WebP/PNG with alpha, content-hashed, its extent in base units.
 */
export interface ReliefLayer {
  file: string;
  rect: [number, number, number, number];
}

export interface ReliefState {
  /** Dark world-land image, above the sea colour, below provinces. */
  inactive: ReliefLayer | null;
  /** Bright land-relief image covering the playable area. */
  playable: ReliefLayer | null;
}

interface ManifestEntry {
  file: string;
  rect: number[]; // [x, y, w, h] in base units
}

function layerEntry(raw: ManifestEntry): ReliefLayer {
  return { file: raw.file, rect: raw.rect as [number, number, number, number] };
}

function loadLayer(entry: ManifestEntry): Promise<ReliefLayer | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(layerEntry(entry));
    img.onerror = () => resolve(null);
    img.src = entry.file;
  });
}

/**
 * One shared download for the whole page session: whoever calls first —
 * the map panel the moment the manifest is known (via sessionCache) or
 * `useRelief` itself — starts the two `Image` requests, every later
 * caller joins the same promise. One request per file, always.
 */
let inflightRelief: Promise<ReliefState> | null = null;

/**
 * Starts the two baked relief downloads at most once per page session
 * and returns the shared promise (null when the bundled manifest has no
 * usable entries — same warning as before). The manifest pointer is
 * bundled and content-hashed, so an unchanged name is
 * immutable-cacheable while a new bake always arrives under a new URL.
 */
export function startReliefDownload(): Promise<ReliefState> | null {
  const raw = manifest as unknown as {
    inactive?: ManifestEntry;
    playable?: ManifestEntry;
  };
  if (!raw.inactive?.file || !raw.playable?.file) {
    console.warn('[relief] manifest has no usable entries');
    return null;
  }
  inflightRelief ??= Promise.all([
    loadLayer(raw.inactive),
    loadLayer(raw.playable),
  ]).then(([inactive, playable]) => {
    if (!inactive && !playable) {
      console.warn('[relief] failed to load relief images', {
        files: [raw.inactive?.file, raw.playable?.file],
      });
    }
    return { inactive, playable };
  });
  return inflightRelief;
}

/** Forget the shared download — called by test stubs for isolation. */
export function clearReliefDownload(): void {
  inflightRelief = null;
}

/**
 * Resolves the two baked relief images — nothing else waits on them and
 * they move with the map through the ordinary world `<g>` transform.
 * The actual requests may already be in flight: `startReliefDownload`
 * is kicked when the map panel learns the manifest, long before the
 * geometry arrives and MapView mounts.
 */
export function useRelief(rules: MapReliefRulesDTO | undefined): ReliefState {
  const [state, setState] = useState<ReliefState>({
    inactive: null,
    playable: null,
  });

  useEffect(() => {
    if (!rules?.enabled) {
      setState({ inactive: null, playable: null });
      return;
    }
    const request = startReliefDownload();
    if (request === null) {
      return;
    }
    let cancelled = false;
    void request.then((images) => {
      if (!cancelled) {
        setState(images);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [rules?.enabled]);

  return state;
}
