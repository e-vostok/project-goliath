/**
 * Map font registry (map2_21): the ONE list of bundled faces every
 * map-text layer — province names, sea names, state names — chooses
 * from. Terminal monospace (the «1960s equipment» look) and condensed
 * sans cuts; all SIL OFL, self-hosted WOFF2 subsets under
 * `public/assets/fonts/` with Latin + Cyrillic + digits + punctuation.
 *
 * Every `family` is a full CSS font-family LIST that ends with the
 * generic family matching the face type — `monospace` or `sans-serif`
 * — so a missing or still-loading bundle can never fall through to
 * the browser's default serif.
 */

/** Config key of a bundled map font (labels.font / labels.sea_font /
 *  states.font all take one of these). */
export type MapFontKey =
  | 'share_tech_mono'
  | 'ibm_plex_mono'
  | 'pt_mono'
  | 'fira_sans_condensed'
  | 'pt_sans_narrow'
  | 'roboto_condensed';

export interface MapFontSpec {
  /** Full CSS stack — always terminates in `monospace`/`sans-serif`. */
  family: string;
  /** The bundled face name alone — probes and @font-face target. */
  face: string;
  /** Fixed-advance face (text fit may assume an em grid). */
  mono: boolean;
  /** The bundle has no italic cut → sea labels get a synthetic skewX
   *  slant instead of `font-style: italic`. */
  syntheticSlant: boolean;
}

export const MAP_FONTS: Record<MapFontKey, MapFontSpec> = {
  share_tech_mono: {
    family: '"Share Tech Mono", monospace',
    face: '"Share Tech Mono"',
    mono: true,
    syntheticSlant: true,
  },
  ibm_plex_mono: {
    family: '"IBM Plex Mono", monospace',
    face: '"IBM Plex Mono"',
    mono: true,
    syntheticSlant: true,
  },
  pt_mono: {
    family: '"PT Mono", monospace',
    face: '"PT Mono"',
    mono: true,
    syntheticSlant: true,
  },
  fira_sans_condensed: {
    family: '"Fira Sans Condensed", sans-serif',
    face: '"Fira Sans Condensed"',
    mono: false,
    syntheticSlant: false,
  },
  pt_sans_narrow: {
    family: '"PT Sans Narrow", sans-serif',
    face: '"PT Sans Narrow"',
    mono: false,
    syntheticSlant: true, // the family ships Regular+Bold only
  },
  roboto_condensed: {
    family: '"Roboto Condensed", sans-serif',
    face: '"Roboto Condensed"',
    mono: false,
    syntheticSlant: false,
  },
};

/** Registry keys in config order — used by tests and docs. */
export const MAP_FONT_KEYS = Object.keys(MAP_FONTS) as MapFontKey[];

/** How long the map waits for a bundled face before warning + staying
 *  on the generic fallback (map2_21). */
export const FONT_LOAD_TIMEOUT_MS = 3000;

/**
 * Ensure a bundled face is usable: `document.fonts.load` a Cyrillic
 * probe, give up after `timeoutMs`. Resolves `true` when the face
 * really serves the probe, `false` when it did not arrive in time or
 * fonts loading is unavailable — callers then keep the generic tail
 * of `spec.family` (never a serif).
 */
export function ensureMapFont(
  face: string,
  timeoutMs = FONT_LOAD_TIMEOUT_MS,
): Promise<boolean> {
  if (
    typeof document === 'undefined' ||
    document.fonts === undefined ||
    typeof document.fonts.load !== 'function'
  ) {
    return Promise.resolve(false);
  }
  const probe = 'Привет Ёё—0123456789';
  const loaded = document.fonts
    .load(`400 16px ${face}`, probe)
    .then(() => document.fonts.check(`400 16px ${face}`, probe))
    .catch(() => false);
  return Promise.race([
    loaded,
    new Promise<boolean>((resolve) =>
      setTimeout(() => resolve(false), timeoutMs),
    ),
  ]);
}
