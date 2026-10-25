/**
 * Nations-section shared building blocks (0.11.0 units 8a/8b) — the
 * panel-local pieces the list and both forms use: PanelCard,
 * PanelButton, the suggestion dropdown, the input/select skins and
 * the fixed Russian select labels. Split out of NationsSection.tsx
 * for unit 8b; behaviour unchanged.
 */

import type { CSSProperties, ReactNode } from 'react';

import { useTheme } from '../../../shared/ui/theme';
import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';

export const PAGE_SIZE = 50;
/** The search fires on a pause, not on every keystroke. */
export const SEARCH_DEBOUNCE_MS = 350;
/** Suggestion lists use the same debounce as the players section. */
export const SUGGEST_DEBOUNCE_MS = 350;
/** The colour status check's pause — the player's form uses 400 ms. */
export const COLOR_CHECK_DEBOUNCE_MS = 400;
/** The owner picker's page size (GET /admin/players?limit=8). */
export const OWNER_SUGGEST_LIMIT = 8;
export const PROVINCE_SUGGEST_LIMIT = 8;

/** The mockup's lowercase labels for the fixed code sets. */
export const GENDER_OPTIONS: Record<string, string> = {
  male: 'мужской',
  female: 'женский',
};
export const SUCCESSION_OPTIONS: Record<string, string> = {
  elections: 'демократические выборы',
  appointment: 'назначение игроком',
  criteria: 'назначение по критериям',
  inheritance: 'наследование',
};

export function PanelCard({
  title,
  aside,
  children,
}: {
  /** No title on screen 03's table card — the mockup heads it nothing. */
  title?: string;
  /** Right end of the title row — captions and counters. */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      style={{
        background: tokenVar('surface'),
        borderRadius: RADII['radius-lg'],
        padding: SPACING['space-4'],
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-3'],
      }}
    >
      {(title !== undefined || aside !== undefined) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {title !== undefined && (
            <h2
              style={{
                margin: 0,
                ...TEXT_STYLES['heading'],
                color: tokenVar('ink'),
              }}
            >
              {title}
            </h2>
          )}
          <span style={{ flexGrow: 1, minWidth: 0 }} />
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

type PanelButtonKind = 'plain' | 'primary' | 'danger' | 'danger-outline';

export function PanelButton({
  kind = 'plain',
  disabled = false,
  onClick,
  children,
  testId,
}: {
  kind?: PanelButtonKind;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const { resolved } = useTheme();
  const onAction = tokenVar(resolved === 'dark' ? 'ground' : 'surface');
  const skin =
    kind === 'primary'
      ? { background: tokenVar('action'), color: onAction, border: 'none' }
      : kind === 'danger'
        ? { background: tokenVar('danger'), color: onAction, border: 'none' }
        : kind === 'danger-outline'
          ? {
              background: 'transparent',
              color: tokenVar('danger'),
              border: `1px solid ${tokenVar('danger')}`,
            }
          : {
              background: tokenVar('surface-inset'),
              color: tokenVar('ink'),
              border: 'none',
            };
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        height: SIZES['button-h'],
        boxSizing: 'border-box',
        padding: '0 16px',
        borderRadius: RADII['radius-md'],
        whiteSpace: 'nowrap',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        ...TEXT_STYLES['body'],
        ...skin,
      }}
    >
      {children}
    </button>
  );
}

/** The .in frame for a select — same skin as the log section's. */
export const controlStyle: CSSProperties = {
  height: SIZES['button-h'],
  boxSizing: 'border-box',
  padding: '0 12px',
  borderRadius: RADII['radius-md'],
  background: tokenVar('surface-inset'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
};

export const inputStyle: CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  height: SIZES['button-h'],
  padding: '0 12px',
  borderRadius: RADII['radius-md'],
  background: tokenVar('surface-inset'),
  border: `1px solid ${tokenVar('ink-faint')}`,
  color: tokenVar('ink'),
  ...TEXT_STYLES['body'],
};

/** One option row inside a suggestion dropdown. */
export function SuggestionList({
  items,
  onPick,
  optionTestId,
  emptyText = 'Ничего не нашлось.',
}: {
  items: ReactNode[];
  onPick: (index: number) => void;
  optionTestId: (index: number) => string;
  emptyText?: string;
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: '100%',
        left: 0,
        right: 0,
        zIndex: 10,
        marginTop: 4,
        background: tokenVar('surface-raised'),
        border: `1px solid ${tokenVar('line')}`,
        borderRadius: RADII['radius-md'],
        overflow: 'hidden',
      }}
    >
      {items.length === 0 ? (
        <div
          style={{
            padding: '8px 12px',
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {emptyText}
        </div>
      ) : (
        items.map((item, index) => (
          <button
            key={index}
            type="button"
            data-testid={optionTestId(index)}
            // mousedown precedes the input's blur, so the pick lands.
            onMouseDown={(event) => {
              event.preventDefault();
              onPick(index);
            }}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 12px',
              border: 'none',
              background: 'transparent',
              color: tokenVar('ink'),
              cursor: 'pointer',
              ...TEXT_STYLES['body'],
            }}
          >
            {item}
          </button>
        ))
      )}
    </div>
  );
}
