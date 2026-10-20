/**
 * useProvinceNames — province id → display name for screens that are
 * not the map (the nation card's «Территория» chips, later unit 14's
 * state subscreen).
 *
 * Names live in the map manifest's `nodes` (`displayName`: `name_ru`
 * with a `name` fallback) — NationDTO deliberately carries only ids
 * (Spec 00_core_ui 9.1). The manifest comes from `useMapManifest`, so
 * a session that already opened the map or the province picker serves
 * the names from the shared session cache without a second download;
 * a cold session loads the manifest once the same way.
 *
 * `loading` is true until the first manifest answer (chips show a
 * neutral placeholder then); an error resolves to an empty map — the
 * caller falls back to «Провинция» and never flashes province numbers.
 */

import { useMemo } from 'react';

import { displayName } from '../lib/search';
import { useMapManifest } from './useMapManifest';

export interface ProvinceNamesState {
  /** Manifest not answered yet — show placeholders, not numbers. */
  loading: boolean;
  names: Map<number, string>;
}

export function useProvinceNames(): ProvinceNamesState {
  const manifest = useMapManifest();

  const names = useMemo(() => {
    const map = new Map<number, string>();
    if (manifest.status === 'ready') {
      for (const node of manifest.manifest.nodes) {
        map.set(node.id, displayName(node));
      }
    }
    return map;
  }, [manifest]);

  return { loading: manifest.status === 'loading', names };
}
