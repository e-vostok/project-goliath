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

/**
 * Loads the two baked relief images lazily after the map has rendered —
 * nothing else waits on them and they move with the map through the
 * ordinary world `<g>` transform. The manifest pointer is bundled and
 * content-hashed, so an unchanged name is immutable-cacheable while a
 * new bake always arrives under a new URL.
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
    let cancelled = false;
    const raw = manifest as unknown as {
      inactive?: ManifestEntry;
      playable?: ManifestEntry;
    };
    if (!raw.inactive?.file || !raw.playable?.file) {
      console.warn('[relief] manifest has no usable entries');
      return;
    }

    const load = (entry: ManifestEntry): Promise<ReliefLayer | null> =>
      new Promise((resolve) => {
        const img = new Image();
        img.onload = () => resolve(layerEntry(entry));
        img.onerror = () => resolve(null);
        img.src = entry.file;
      });

    Promise.all([load(raw.inactive), load(raw.playable)]).then(
      ([inactive, playable]) => {
        if (cancelled) return;
        if (!inactive && !playable) {
          console.warn('[relief] failed to load relief images', {
            files: [raw.inactive?.file, raw.playable?.file],
          });
        }
        setState({ inactive, playable });
      },
    );

    return () => {
      cancelled = true;
    };
  }, [rules?.enabled]);

  return state;
}
