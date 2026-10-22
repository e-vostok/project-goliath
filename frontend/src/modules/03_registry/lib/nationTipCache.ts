/**
 * The session cache of the nation «Подсказка» (version 0.9.0 unit 11):
 * one `GET /nations/{id}` public-card fetch per nation id lives for 60
 * seconds, so a second hover within a minute is instant and repeated
 * hovering never floods the server. A failed request is NOT cached —
 * the next hover retries.
 */

import { api } from '../../../shared/api-client';
import type { NationPublicDTO } from '../../../shared/types';

/** How long a fetched card stays fresh (ms). */
export const NATION_TIP_TTL_MS = 60_000;

interface CacheEntry {
  at: number;
  nation: NationPublicDTO;
}

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<NationPublicDTO>>();

export function fetchNationTip(
  token: string,
  nationId: string,
): Promise<NationPublicDTO> {
  const hit = cache.get(nationId);
  if (hit !== undefined && Date.now() - hit.at < NATION_TIP_TTL_MS) {
    return Promise.resolve(hit.nation);
  }
  const running = inflight.get(nationId);
  if (running !== undefined) {
    return running;
  }
  const request = api
    .getNation(token, nationId)
    .then((nation) => {
      cache.set(nationId, { at: Date.now(), nation });
      return nation;
    })
    .finally(() => {
      inflight.delete(nationId);
    });
  inflight.set(nationId, request);
  return request;
}

/** Test aid — clears the session cache. */
export function clearNationTipCache(): void {
  cache.clear();
  inflight.clear();
}
