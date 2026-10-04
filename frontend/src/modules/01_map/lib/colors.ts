/**
 * Node colouring — Spec Part 5 («Клиентские компоненты»), pure.
 *
 * Fill order: owner colour (MapNationDTO.color_hex via state.owners) →
 * LAND without owner takes colors.neutral_province, SEA takes
 * colors.sea. The outside path uses colors.outside and the background
 * colors.inland_water — handled in MapView.
 */

import type {
  MapNationDTO,
  MapNodeDTO,
  MapStateDTO,
  MapViewRulesDTO,
} from '../types';

export type ColorRules = MapViewRulesDTO['colors'];

/**
 * province_id → owning nation, from a state payload. Owners reference
 * `nations` by index; free provinces are simply absent from the map.
 *
 * `validIds` (the manifest node-id set, a Set or an id-keyed Map)
 * guards against entries for nodes outside the active manifest —
 * e.g. a retired node left in a stale payload (Spec 1.9): such owner
 * records are dropped instead of colouring a non-existent path.
 */
export function buildOwnerMap(
  state: MapStateDTO | null,
  validIds?: { has(id: number): boolean },
): Map<number, MapNationDTO> {
  const owners = new Map<number, MapNationDTO>();
  if (!state) {
    return owners;
  }
  for (const [provinceId, nationIndex] of state.owners) {
    if (validIds && !validIds.has(provinceId)) {
      continue;
    }
    const nation = state.nations[nationIndex];
    if (nation) {
      owners.set(provinceId, nation);
    }
  }
  return owners;
}

export function nodeFill(
  node: MapNodeDTO,
  owner: MapNationDTO | undefined,
  colors: ColorRules,
): string {
  if (node.kind === 'SEA') {
    return colors.sea;
  }
  return owner ? owner.color_hex : colors.neutral_province;
}
