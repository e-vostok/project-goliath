/**
 * Brand mark (UI Spec 4): the 38 px project logo picked by the resolved
 * theme and the «PAX ATOMICA» wordmark in Big Shoulders Display 800
 * with 0.1 em tracking.
 */

import { useTheme } from './theme';
import { FONTS, tokenVar } from './tokens';

export function BrandMark() {
  const { resolved } = useTheme();
  const dark = resolved === 'dark';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      {/* WebP first (76 px source, ~3 KB), PNG stays the fallback for
          engines without WebP — same artwork, same 38 px mark. */}
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
          width={38}
          height={38}
          alt="Логотип PAX ATOMICA"
          style={{ display: 'block' }}
        />
      </picture>
      <span
        style={{
          fontFamily: FONTS.wordmark,
          fontWeight: 800,
          fontSize: 24,
          lineHeight: '28px',
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
