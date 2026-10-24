/**
 * useProvinceNames — province id → display name for screens that are
 * not the map (the nation card's «Территория» chips, registration
 * territories, the nation subscreen).
 *
 * Names come from GET /map/province-names (load-speed unit 11): the
 * light id → display-name payload these callers need — downloading
 * the full manifest (~103 KB gz) for ~5 KB of names is what unit 10's
 * research flagged. The server resolves the display-name rule
 * (`name_ru` over `name` over key), so the answer is used verbatim.
 *
 * Caching mirrors `useMapManifest`: the last { etag, body } pair lives
 * in the session cache (lib/sessionCache), mirrored to localStorage
 * under an app-version key, so a repeat launch sends `If-None-Match`
 * and a 304 reuses the stored body. A warm copy renders instantly
 * while the conditional request revalidates in the background.
 *
 * `loading` is true until the first answer (chips show a neutral
 * placeholder then); an error resolves to an empty map — the caller
 * falls back to «Провинция» and never flashes province numbers.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { mapApi } from '../api';
import { decideConditional } from '../lib/cache';
import { readNamesCache, writeNamesCache } from '../lib/sessionCache';
import type { MapProvinceNamesDTO } from '../types';
import { useSession } from '../../00_core/hooks/useAuth';

export interface ProvinceNamesState {
  /** Names not answered yet — show placeholders, not numbers. */
  loading: boolean;
  names: Map<number, string>;
}

export function useProvinceNames(): ProvinceNamesState {
  const { token } = useSession();
  const [dto, setDto] = useState<MapProvinceNamesDTO | null>(
    () => readNamesCache()?.body ?? null,
  );
  const [loading, setLoading] = useState(dto === null);

  const load = useCallback(
    async (conditional: boolean, signal?: AbortSignal): Promise<void> => {
      const cached = readNamesCache();
      const answer = await mapApi.getProvinceNames(
        token,
        conditional ? cached?.etag : null,
        signal,
      );
      const decision = decideConditional(answer, cached);
      if (decision.action === 'refetch-unconditional') {
        return load(false, signal);
      }
      writeNamesCache(decision.value);
      setDto(decision.value.body);
      setLoading(false);
    },
    [token],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(true, controller.signal).catch(() => {
      // A failed fetch resolves to empty names — the callers' fallback
      // («Провинция») is unchanged from when the manifest failed.
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    });
    return () => controller.abort();
  }, [load]);

  const names = useMemo(() => {
    const map = new Map<number, string>();
    if (dto !== null) {
      for (const [id, name] of Object.entries(dto.names)) {
        map.set(Number(id), name);
      }
    }
    return map;
  }, [dto]);

  return { loading, names };
}
