/**
 * Tokens (UI Spec 5.1): both themes define exactly the same set of
 * colour tokens, and every token of the spec is present — a theme that
 * forgot a colour fails here before any window is built.
 */

import { THEME_COLORS } from '../tokens';
import type { ColorToken } from '../tokens';

const SPEC_5_1_TOKENS: ColorToken[] = [
  'ground',
  'surface',
  'surface-raised',
  'surface-inset',
  'line',
  'ink',
  'ink-muted',
  'ink-faint',
  'action',
  'link',
  'signal',
  'on-signal',
  'signal-ink',
  'danger',
  'positive',
  'warning-bg',
  'swatch-edge',
];

describe('THEME_COLORS', () => {
  it('defines exactly the same token set in both themes', () => {
    const dark = Object.keys(THEME_COLORS.dark).sort();
    const light = Object.keys(THEME_COLORS.light).sort();
    expect(light).toEqual(dark);
  });

  it('contains every colour token of Spec 5.1', () => {
    for (const token of SPEC_5_1_TOKENS) {
      expect(THEME_COLORS.dark[token]).toBeTruthy();
      expect(THEME_COLORS.light[token]).toBeTruthy();
    }
    expect(Object.keys(THEME_COLORS.dark).sort()).toEqual(
      [...SPEC_5_1_TOKENS].sort(),
    );
  });
});
