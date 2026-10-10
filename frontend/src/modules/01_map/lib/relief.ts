/**
 * Relief underlay (map2_5): lazy loader for the baked Natural Earth
 * image. The map never waits for it — the hook starts the fetch after
 * mount and flips to `active` when the pixels actually arrived, so the
 * layer fades in on a usable map and a 404/network failure simply
 * leaves the classic look (one console warning, no retry storm).
 *
 * The file name and the world-space rect come from the generated
 * `relief/manifest.json` (written by tools/map_pipeline/build_relief.py);
 * the hash in the name makes it safe to cache as immutable.
 */

import { useEffect, useState } from 'react';

import reliefAsset from '../relief/manifest.json';
import type { MapReliefRulesDTO } from '../types';

export interface ReliefLayer {
  url: string;
  /** [x, y, width, height] in world (view_box) units. */
  rect: [number, number, number, number];
}

/**
 * The loaded relief layer, or null while loading / when disabled /
 * after a load failure.
 */
export function useRelief(
  rules: MapReliefRulesDTO | undefined,
): ReliefLayer | null {
  const enabled = rules?.enabled === true;
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (!cancelled) {
        setLoaded(true);
      }
    };
    img.onerror = () => {
      console.warn('01_map: relief image failed to load:', reliefAsset.file);
    };
    img.src = reliefAsset.file;
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  if (!enabled || !loaded) {
    return null;
  }
  return {
    url: reliefAsset.file,
    rect: reliefAsset.rect as ReliefLayer['rect'],
  };
}
