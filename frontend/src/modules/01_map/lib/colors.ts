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
 */
export function buildOwnerMap(
  state: MapStateDTO | null,
): Map<number, MapNationDTO> {
  const owners = new Map<number, MapNationDTO>();
  if (!state) {
    return owners;
  }
  for (const [provinceId, nationIndex] of state.owners) {
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
