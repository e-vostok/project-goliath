/**
 * Adjacency over manifest edges, for NodeCard's neighbour list — pure.
 */

import type { MapEdgeDTO, MapEdgeType } from '../types';

export interface NeighbourRef {
  nodeId: number;
  edge: MapEdgeDTO;
}

/** node id → its neighbours with the connecting edge. */
export function buildAdjacency(
  edges: MapEdgeDTO[],
): Map<number, NeighbourRef[]> {
  const adjacency = new Map<number, NeighbourRef[]>();
  for (const edge of edges) {
    for (const [from, to] of [
      [edge.a, edge.b],
      [edge.b, edge.a],
    ] as const) {
      const list = adjacency.get(from);
      const ref: NeighbourRef = { nodeId: to, edge };
      if (list) {
        list.push(ref);
      } else {
        adjacency.set(from, [ref]);
      }
    }
  }
  return adjacency;
}

/** Edge kind in words (Russian UI text, Spec Part 5 NodeCard). */
export const EDGE_TYPE_LABELS: Record<MapEdgeType, string> = {
  land: 'сухопутная граница',
  coast: 'побережье',
  sea: 'морская связь',
  strait: 'пролив',
};

/** «проходимость 50 %» for a strait edge, else null. */
export function straitMultiplierLabel(edge: MapEdgeDTO): string | null {
  if (edge.type !== 'strait' || edge.multiplier === null) {
    return null;
  }
  return `проходимость ${Math.round(edge.multiplier * 100)} %`;
}
