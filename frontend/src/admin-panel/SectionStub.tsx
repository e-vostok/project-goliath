/**
 * Section placeholder (0.11.0 unit 5a): every registered section shows
 * the same «Раздел готовится» card until units 6–11 fill it in.
 * The h1 title keeps the mockup-02 look — section icon in signal-ink,
 * title-uppercase text.
 */

import { RADII, TEXT_STYLES, tokenVar } from '../shared/ui/tokens';
import type { PanelIconName } from './panelIcons';
import { PanelIcon } from './panelIcons';

export function SectionStub({
  icon,
  title,
}: {
  icon: PanelIconName;
  title: string;
}) {
  return (
    <>
      <h1
        style={{
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          ...TEXT_STYLES['title-uppercase'],
          fontSize: 24,
          lineHeight: '28px',
        }}
      >
        <PanelIcon name={icon} accent size={20} />
        {title}
      </h1>
      <div
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: 16,
          ...TEXT_STYLES['body'],
        }}
      >
        <span style={{ color: tokenVar('ink-muted') }}>
          Раздел готовится.
        </span>
      </div>
    </>
  );
}
