/**
 * Label rule — Spec 3.9, pure functions.
 *
 * A node's label is shown iff its on-screen width reaches
 * `label_min_width_px`: s · wᵢ ≥ min width, where wᵢ is the node bbox
 * width in world units.
 */

import type { MapNodeDTO } from '../types';

/** Whether one node qualifies for a label at scale `s`. */
export function labelVisible(
  node: MapNodeDTO,
  s: number,
  labelMinWidthPx: number,
): boolean {
  return s * (node.bbox[2] - node.bbox[0]) >= labelMinWidthPx;
}

/** Nodes whose labels are visible at scale `s`. */
export function visibleLabelNodes(
  nodes: MapNodeDTO[],
  s: number,
  labelMinWidthPx: number,
): MapNodeDTO[] {
  if (!Number.isFinite(s) || s <= 0) {
    return [];
  }
  return nodes.filter((node) => labelVisible(node, s, labelMinWidthPx));
}
