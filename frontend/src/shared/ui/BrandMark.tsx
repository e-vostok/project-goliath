/**
 * Brand mark (UI Spec 4): the 38 px project logo picked by the resolved
 * theme and the «PAX ATOMICA» wordmark in Big Shoulders Display 800
 * with 0.1 em tracking.
 */

import { useTheme } from './theme';
import { FONTS, tokenVar } from './tokens';

export function BrandMark() {
  const { resolved } = useTheme();
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <img
        src={
          resolved === 'dark'
            ? '/assets/brand/logo-white.png'
            : '/assets/brand/logo-dark.png'
        }
        width={38}
        height={38}
        alt="Логотип PAX ATOMICA"
        style={{ display: 'block' }}
      />
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
