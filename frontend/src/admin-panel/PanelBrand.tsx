/**
 * Panel brand mark (mockups 0.11.0 screens 02/09): the project logo
 * at 32 px and «PAX ATOMICA» in the heading font (20 px, 500, .1 em)
 * — deliberately smaller than the Mini App's BrandMark (38 px / 24 px
 * poster font). Same artwork files, picked by the resolved theme.
 */

import { FONTS, tokenVar } from '../shared/ui/tokens';
import { useTheme } from '../shared/ui/theme';

export function PanelBrand() {
  const { resolved } = useTheme();
  const dark = resolved === 'dark';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        flexShrink: 0,
      }}
    >
      <picture>
        <source
          srcSet={
            dark
              ? '/assets/brand/logo-white.webp'
              : '/assets/brand/logo-dark.webp'
          }
          type="image/webp"
        />
        <img
          src={
            dark
              ? '/assets/brand/logo-white.png'
              : '/assets/brand/logo-dark.png'
          }
          width={32}
          height={32}
          alt="Логотип PAX ATOMICA"
          style={{ display: 'block' }}
        />
      </picture>
      <span
        style={{
          fontFamily: FONTS.heading,
          fontWeight: 500,
          fontSize: 20,
          lineHeight: '24px',
          letterSpacing: '.1em',
          color: tokenVar('ink'),
          whiteSpace: 'nowrap',
        }}
      >
        PAX ATOMICA
      </span>
    </span>
  );
}
