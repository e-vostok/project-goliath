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

/** Node card width, px (Spec Part 5: «около 280 px»). */
export const NODECARD_WIDTH_PX = 280;
