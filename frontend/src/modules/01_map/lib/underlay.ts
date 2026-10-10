/**
 * Seam cover underlay (map2_13), pure.
 *
 * Neighbouring province fills do not overlap exactly — anti-aliasing
 * leaves a hairline of whatever is UNDER the fills along every shared
 * edge, and that used to be the sea-coloured background rect. The fix
 * is one compound path of every shared edge in `borders.json` (the
 * 2621 LAND–LAND pair polylines, internal and state alike), drawn
 * UNDER the fills with a thin `colors.land_underlay` stroke. The
 * stroke hugs the crack itself: wherever a hairline void opens
 * between two fills, land colour — never sea — shows through.
 *
 * Why this shape and not a filled union of the LAND polygons:
 * - A union fill is fully occluded by the fills above it — identical
 *   geometry, identical cracks, zero coverage of the voids.
 * - A stroked union (fill + 1 px stroke) does cover cracks but the
 *   per-settle re-raster of ~97K stroked vertices measured 250 ms at
 *   4× CPU; the pair compound is ~39K vertices and is clipped to the
 *   viewport, measuring ≈7 ms across all benchmark zoom levels.
 * - The stroke width is in world units (no non-scaling-stroke): the
 *   cracks are world-space voids, and a non-scaling stroke forces a
 *   re-stroke on every transform change — that alone was the 250 ms.
 *
 * Real water is untouched: every pair polyline connects two LAND
 * nodes, so the stroke never runs along a coast or a strait, and
 * channels wider than the stroke keep showing the sea beneath.
 *
 * The path depends on `borders.json` only — never on ownership — so
 * it is built once and never reclassified.
 */

import type { MapBordersDTO } from '../types';

/** Combined `d` of every shared-edge pair polyline. */
export function buildSeamCover(borders: MapBordersDTO | null): string {
  if (borders === null) {
    return '';
  }
  return Object.values(borders.pairs).join(' ');
}
