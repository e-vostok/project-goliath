/**
 * Subscreen — the «Подэкран» frame (UI Spec 3.2). It replaces the
 * parent's content in the same window (never lies over it, never
 * wider than `win-screen` = 910 px): under the top bar sits the
 * return band — 48 px, `surface-raised`, a 4 px `action` mark on its
 * left edge — with the «← parent» button and the path chain
 * «Реестр / … / Name». Preceding segments are `ink-muted`, the last
 * one (the current place) is `ink`; segments are separated by « / »,
 * long names ellipsize, the band never wraps. The children sit below
 * in the normal screen padding. There is no «Подэкран» word on
 * screen — the band itself says what kind of window this is — and
 * Esc does not go back. The parent screen stays mounted behind the
 * subscreen (hidden, not unmounted), so returning restores its tab,
 * filters, search and scroll exactly.
 */

import { Fragment, type ReactNode } from 'react';
import { Icon16ArrowLeftOutline } from '@vkontakte/icons';
import { Button } from '@vkontakte/vkui';

import { SIZES, SPACING, TEXT_STYLES, tokenVar } from './tokens';

export function Subscreen({
  parentLabel,
  trail,
  onBack,
  children,
}: {
  /** The parent screen's name — the «← …» button and chain root. */
  parentLabel: string;
  /** Path segments after the parent; the last one is the current place. */
  trail: string[];
  /** «← parent» click — leads back to the window the player came from. */
  onBack: () => void;
  children?: ReactNode;
}) {
  const segments = [parentLabel, ...trail];
  return (
    <div
      data-testid="subscreen"
      style={{
        maxWidth: SIZES['win-screen'],
        boxSizing: 'border-box',
        background: tokenVar('ground'),
      }}
    >
      <div
        data-testid="subscreen-band"
        style={{
          position: 'relative',
          height: SIZES['topbar-h'],
          boxSizing: 'border-box',
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
          paddingLeft: SPACING['space-3'],
          paddingRight: SPACING['space-4'],
          background: tokenVar('surface-raised'),
          borderBottom: `1px solid ${tokenVar('line')}`,
          overflow: 'hidden',
          whiteSpace: 'nowrap',
        }}
      >
        <span
          aria-hidden
          data-testid="subscreen-mark"
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: 4,
            background: tokenVar('action'),
          }}
        />
        <Button
          mode="tertiary"
          size="s"
          before={<Icon16ArrowLeftOutline width={16} height={16} />}
          onClick={onBack}
          data-testid="subscreen-back"
          aria-label={`← ${parentLabel}`}
          style={{ flexShrink: 0 }}
        >
          {parentLabel}
        </Button>
        <div
          data-testid="subscreen-trail"
          aria-label={segments.join(' / ')}
          style={{
            ...TEXT_STYLES['body'],
            display: 'flex',
            alignItems: 'center',
            minWidth: 0,
            flex: 1,
            overflow: 'hidden',
            whiteSpace: 'nowrap',
          }}
        >
          {segments.map((segment, i) => (
            <Fragment key={i}>
              {i > 0 && (
                <span
                  aria-hidden
                  style={{ color: tokenVar('ink-faint'), flexShrink: 0 }}
                >
                  {' / '}
                </span>
              )}
              <span
                title={segment}
                style={{
                  color:
                    i === segments.length - 1
                      ? tokenVar('ink')
                      : tokenVar('ink-muted'),
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  minWidth: 0,
                  flexShrink: 1,
                }}
              >
                {segment}
              </span>
            </Fragment>
          ))}
        </div>
      </div>
      <div
        style={{
          padding: SPACING['space-4'],
          display: 'flex',
          flexDirection: 'column',
          gap: SPACING['space-3'],
        }}
      >
        {children}
      </div>
    </div>
  );
}
