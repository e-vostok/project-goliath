/**
 * Nation colour swatch (UI Spec 6, элемент 7): 16 px square,
 * `radius-sm`, `swatch-edge` border, HEX in `figure` next to it. The
 * `hex` prop is game data (a nation's colour), not a design token.
 */

import { FONTS, RADII, tokenVar } from './tokens';

export function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: RADII['radius-sm'],
          background: hex,
          border: `1px solid ${tokenVar('swatch-edge')}`,
          boxSizing: 'border-box',
        }}
      />
      <span
        style={{
          fontFamily: FONTS.mono,
          fontSize: 12,
          lineHeight: '16px',
          color: tokenVar('ink'),
          textTransform: 'uppercase',
        }}
      >
        {hex}
      </span>
    </span>
  );
}
