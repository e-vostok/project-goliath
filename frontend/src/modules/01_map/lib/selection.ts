/**
 * Pure selection logic for `MapView mode="select"` / `ProvincePicker`
 * (Spec Part 5; connectivity per Spec 3.3 — `land` and `strait` edges).
 *
 * Everything here is advisory: the server's POST /map/starting-group/check
 * and the registration itself stay authoritative (INV-M8). No limits or
 * rules are hardcoded — `max`/`min` arrive through the context/limits
 * arguments and may be null while GET /nations/rules has not resolved
 * (or has failed); the picker then stays open-ended and the server decides.
 */

import { buildAdjacency } from './adjacency';
import type { BBox } from './view';
import type {
  MapEdgeDTO,
  MapEdgeType,
  MapNationDTO,
  MapNodeDTO,
} from '../types';

/** What a click on the map needs to know to judge a node. */
export interface SelectionContext {
  nodes: Map<number, MapNodeDTO>;
  /** province_id → owning nation (empty while the state has not loaded). */
  owners: Map<number, MapNationDTO>;
  /** Upper bound from /nations/rules; null while the rules are unknown. */
  max: number | null;
}

export type SelectableReason = 'OK' | 'SEA' | 'OCCUPIED';

/** Selectable = LAND node that is free in the current state. */
export function isSelectable(
  node: MapNodeDTO,
  ctx: Pick<SelectionContext, 'owners'>,
): SelectableReason {
  if (node.kind !== 'LAND') {
    return 'SEA';
  }
  return ctx.owners.has(node.id) ? 'OCCUPIED' : 'OK';
}

export type ToggleRefusal =
  | 'NOT_FOUND'
  | 'SEA'
  | 'OCCUPIED'
  | 'MAX_REACHED';

export type ToggleResult =
  | { ok: true; selection: number[] }
  | { ok: false; reason: ToggleRefusal };

/**
 * Click semantics: a selected id toggles off (always allowed); a new id
 * is appended unless the node is unknown, sea, occupied, or the upper
 * bound is already reached. The selection order is the click order —
 * that is the ordered id list the registration request sends.
 */
export function toggle(
  selection: readonly number[],
  id: number,
  ctx: SelectionContext,
): ToggleResult {
  const index = selection.indexOf(id);
  if (index >= 0) {
    const next = selection.slice();
    next.splice(index, 1);
    return { ok: true, selection: next };
  }
  const node = ctx.nodes.get(id);
  if (!node) {
    return { ok: false, reason: 'NOT_FOUND' };
  }
  const reason = isSelectable(node, ctx);
  if (reason !== 'OK') {
    return { ok: false, reason };
  }
  if (ctx.max !== null && selection.length >= ctx.max) {
    return { ok: false, reason: 'MAX_REACHED' };
  }
  return { ok: true, selection: [...selection, id] };
}

/** Edge types that connect provinces into one group (Spec 3.3). */
export const CONNECTING_EDGE_TYPES: ReadonlySet<MapEdgeType> = new Set([
  'land',
  'strait',
]);

/**
 * Connected components of the selection, restricted to the selected
 * nodes: BFS over land/strait edges reusing the Issue-5 adjacency
 * builder. Empty selection -> []; duplicate ids collapse silently.
 */
export function components(
  selection: readonly number[],
  edges: MapEdgeDTO[],
): number[][] {
  if (selection.length === 0) {
    return [];
  }
  const wanted = new Set(selection);
  const adjacency = buildAdjacency(
    edges.filter((edge) => CONNECTING_EDGE_TYPES.has(edge.type)),
  );
  const seen = new Set<number>();
  const parts: number[][] = [];
  for (const start of selection) {
    if (seen.has(start)) {
      continue;
    }
    const part: number[] = [];
    const queue = [start];
    seen.add(start);
    while (queue.length > 0) {
      const id = queue.pop() as number;
      part.push(id);
      for (const ref of adjacency.get(id) ?? []) {
        if (wanted.has(ref.nodeId) && !seen.has(ref.nodeId)) {
          seen.add(ref.nodeId);
          queue.push(ref.nodeId);
        }
      }
    }
    parts.push(part);
  }
  return parts;
}

/** Russian plural of «часть» for the connectivity indicator. */
function pluralParts(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return 'часть';
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return 'части';
  }
  return 'частей';
}

/**
 * Indicator text (Spec Part 5): null for an empty selection,
 * «Территория связна» for one component, «Не связна: N частей»
 * otherwise.
 */
export function describeConnectivity(componentCount: number): string | null {
  if (componentCount <= 0) {
    return null;
  }
  if (componentCount === 1) {
    return 'Территория связна';
  }
  return `Не связна: ${componentCount} ${pluralParts(componentCount)}`;
}

export interface SelectionLimits {
  /** From NationRulesDTO.min_provinces; null while rules are unknown. */
  min: number | null;
  /** From NationRulesDTO.max_provinces; null while rules are unknown. */
  max: number | null;
}

/**
 * «Готово» gating: the count must be within [min, max] (null bounds are
 * unknown, not violated) and, when manifest.rules.require_connected_start
 * is set, the selection must be a single component over land/strait
 * edges. With the rule off the indicator is informational only.
 */
export function isSelectionValid(
  selection: readonly number[],
  rules: { require_connected_start: boolean },
  limits: SelectionLimits,
  edges: MapEdgeDTO[],
): boolean {
  const count = selection.length;
  if (count === 0) {
    return false;
  }
  if (limits.min !== null && count < limits.min) {
    return false;
  }
  if (limits.max !== null && count > limits.max) {
    return false;
  }
  if (
    rules.require_connected_start &&
    components(selection, edges).length !== 1
  ) {
    return false;
  }
  return true;
}

/**
 * Union of the selected nodes' bboxes — the initial fit target of the
 * picker map. Null when nothing known is selected (caller then fits the
 * whole playable area instead).
 */
export function fitBBoxOfSelection(
  selection: readonly number[],
  nodes: Map<number, MapNodeDTO>,
): BBox | null {
  let box: BBox | null = null;
  for (const id of selection) {
    const node = nodes.get(id);
    if (!node) {
      continue;
    }
    const [x0, y0, x1, y1] = node.bbox;
    box =
      box === null
        ? [x0, y0, x1, y1]
        : [
            Math.min(box[0], x0),
            Math.min(box[1], y0),
            Math.max(box[2], x1),
            Math.max(box[3], y1),
          ];
  }
  return box;
}

/** Russian plural of «провинция». */
function pluralProvinces(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) {
    return 'провинция';
  }
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return 'провинции';
  }
  return 'провинций';
}

/** Hint shown briefly under the header when a click is refused. */
export function refusalHint(
  reason: ToggleRefusal,
  max: number | null,
): string {
  switch (reason) {
    case 'SEA':
      return 'Морскую зону выбрать нельзя';
    case 'OCCUPIED':
      return 'Эта провинция уже занята';
    case 'MAX_REACHED':
      return max === null
        ? 'Выбрано максимум провинций'
        : `Выбрано максимум — ${max} ${pluralProvinces(max)}`;
    case 'NOT_FOUND':
      return 'Провинция не найдена на карте';
  }
}

/**
 * Tooltip status line in select mode (Spec Part 5):
 * free land «свободна», occupied «занята: ИмяГосударства»,
 * sea «морская зона, выбрать нельзя».
 */
export function selectTooltipStatus(
  node: MapNodeDTO,
  owner: MapNationDTO | undefined,
): string {
  if (node.kind === 'SEA') {
    return 'морская зона, выбрать нельзя';
  }
  return owner ? `занята: ${owner.name}` : 'свободна';
}
