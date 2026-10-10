/**
 * Purely technical UI constants for 01_map — pixel/millisecond values with
 * no balance meaning. Everything the player can feel (zoom limits, pan
 * margin, label width, search limits, colours, refresh timings, the
 * big-window switch) comes from `manifest.rules` instead — see
 * MapViewRulesDTO — and must not be duplicated here.
 */

/** Mouse travel below this many px counts as a click, not a drag. */
export const DRAG_THRESHOLD_PX = 4;

/** Quiet period after the last wheel/drag event before a gesture is
 *  considered settled and React state is committed (labels re-render). */
export const GESTURE_SETTLE_MS = 160;

/** Tooltip offset from the cursor, px. */
export const TOOLTIP_OFFSET_PX = 14;

/** Extra margin when the view is fitted to a node bbox (search result). */
export const FOCUS_BBOX_MARGIN = 1.2;

/** Node label font size on screen, px (kept constant across zoom). */
export const LABEL_FONT_PX = 13;

/** Halo around label text for readability over any fill, px. */
export const LABEL_HALO_PX = 3;

/** Label text colour — fixed UI chrome, not a map colour rule. */
export const LABEL_TEXT_COLOR = '#F2F3F5';

/** Label halo colour — fixed UI chrome. */
export const LABEL_HALO_COLOR = 'rgba(0,0,0,0.75)';

/** Stroke width of the hover overlay outline, px (screen-constant). */
export const OVERLAY_STROKE_PX = 2;

/** Width of the per-node seam-cover stroke, in map units (map2_13). */
export const SEAM_STROKE_W = 0.05;

/**
 * Width of the seam-cover stroke in the non-scaling band, in device
 * pixels (map2_14): below SEAM_NSS_MAX_S a hairline device-space
 * stroke rasterises far faster per frame than a subpixel world-space
 * one, and ~1 px still covers every crack — they are world-space
 * voids of at most ~0.05 u, which render well under a pixel there.
 */
export const SEAM_STROKE_PX = 1.2;

/**
 * Scale below which the seam-cover stroke is switched off entirely
 * (map2_14): the widest crack it can cover is SEAM_STROKE_W map units,
 * which renders under a third of a pixel below this zoom — invisible
 * even if uncovered. Gating the stroke off there removes a subpixel
 * anti-aliased re-stroke of every visible fill each frame.
 */
export const SEAM_MIN_S = 6;

/**
 * Scale above which the seam cover switches from the non-scaling
 * hairline back to the world-space SEAM_STROKE_W (map2_14): at high
 * zoom the world width already renders ~a pixel, and the per-frame
 * device-space re-stroke of ~1000 paths during a zoom costs more
 * than it saves.
 */
export const SEAM_NSS_MAX_S = 12;

/** Node card width, px (Spec Part 5: «около 280 px»). */
export const NODECARD_WIDTH_PX = 280;
