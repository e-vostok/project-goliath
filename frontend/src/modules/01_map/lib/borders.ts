/**
 * Border-layer classification (map2_4), pure.
 *
 * `borders.json` gives one canonical polyline per adjacent land pair
 * (`pairs`, keyed "a-b") and one coastline per node (`coasts`, keyed by
 * node id — covers sea, excluded land and the map edge). The client
 * does not know which pair is a state border until ownership arrives
 * in the state payload, so the paths are classified here, not in the
 * pipeline:
 *
 * - pair → STATE when the two owners differ, counting a free province
 *   as «no owner»: owned-vs-free is a state border, free-vs-free and
 *   same-nation are INTERNAL;
 * - every coast entry → COAST, owned or free (there is no thick state
 *   line along the sea; island parts of a node are pure coast).
 *
 * The three results are single compound path strings — the layer draws
 * three <path> elements, not thousands.
 */

import type { MapBordersDTO, MapNationDTO } from '../types';

export interface BorderPaths {
  /** Thin solid line between provinces of one owner (or both free). */
  internal: string;
  /** Solid thick line along land borders between different owners. */
  state: string;
  /** Thin line along every node's coast — always present. */
  coast: string;
}

/**
 * Combine `borders` into three path strings under the given owners map
 * (province id → nation, absent = free). Nation identity is object
 * identity — `buildOwnerMap` hands every province of a nation the same
 * `MapNationDTO` instance, and two distinct past-turn nations must stay
 * distinct even when both carry `id: null`.
 */
export function buildBorderPaths(
  borders: MapBordersDTO,
  owners: ReadonlyMap<number, MapNationDTO>,
): BorderPaths {
  const internal: string[] = [];
  const state: string[] = [];
  const coast: string[] = [];
  for (const [key, d] of Object.entries(borders.pairs)) {
    const [a, b] = key.split('-').map(Number);
    if (owners.get(a) === owners.get(b)) {
      internal.push(d);
    } else {
      state.push(d);
    }
  }
  for (const d of Object.values(borders.coasts)) {
    coast.push(d);
  }
  return {
    internal: internal.join(' '),
    state: state.join(' '),
    coast: coast.join(' '),
  };
}
