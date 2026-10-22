/**
 * The four-tab strip of the registration window (UI Spec 9.6 — version
 * 0.9.0 unit 8c): «Основные данные и символика», «Глава государства»,
 * «История», «Территории». Each tab shows a numbered round mark, the
 * active tab carries an `action` underline, an inactive tab that needs
 * attention shows a small `danger` dot. Titles never truncate — every
 * tab is `flex: 1 1 auto` so it takes its fair share of the row.
 *
 * Arrow keys move the focus, a click switches the tab (the draft keeps
 * everything); marks come from the container (`fieldToTab` over the
 * server errors plus the required fields the player left empty).
 */

import { useCallback } from 'react';

import {
  RADII,
  TEXT_STYLES,
  tokenVar,
  type BlockIconName,
} from '../../../shared/ui';
import type { RegistrationTab } from './registrationForm';

export interface CreateNationTabBarProps {
  /** Active tab 1..4 — the strip is a pick-one-of-4 radio group. */
  tab: RegistrationTab;
  onTabChange: (tab: RegistrationTab) => void;
  /** Marks of the inactive tabs that hold an error or a missing field. */
  tabMarks: Record<RegistrationTab, boolean>;
}

/** Title + block icon of each tab — the strip and the tab blocks share it. */
export const CREATE_NATION_TABS: Array<{
  title: string;
  icon: BlockIconName;
}> = [
  { title: 'Основные данные и символика', icon: 'list' },
  { title: 'Глава государства', icon: 'person' },
  { title: 'История', icon: 'text' },
  { title: 'Территории', icon: 'map' },
];

export function CreateNationTabBar({
  tab,
  onTabChange,
  tabMarks,
}: CreateNationTabBarProps) {
  const onRadioArrow = useCallback((key: string, index: number) => {
    const step = key === 'ArrowRight' ? 1 : -1;
    const next =
      ((index + step + CREATE_NATION_TABS.length) % CREATE_NATION_TABS.length) +
      1;
    const input = document.querySelector<HTMLElement>(
      `[data-testid="step-title-${next}"]`,
    );
    input?.focus();
  }, []);

  return (
    <div
      role="radiogroup"
      aria-label="Разделы регистрации"
      style={{ display: 'flex', gap: 4 }}
    >
      {CREATE_NATION_TABS.map(({ title }, index) => {
        const value = (index + 1) as RegistrationTab;
        const active = value === tab;
        const marked = tabMarks[value] && !active;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            data-testid={`step-title-${value}`}
            onClick={() => onTabChange(value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                onRadioArrow(e.key, index);
              }
            }}
            style={{
              flex: '1 1 auto',
              minWidth: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
              padding: '4px 4px 0',
              border: 'none',
              background: 'none',
              cursor: 'pointer',
            }}
          >
            <span
              style={{
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: 24,
                height: 24,
                borderRadius: RADII['radius-pill'],
                border: `1px solid ${tokenVar(active ? 'action' : 'ink-faint')}`,
                background: tokenVar(active ? 'action' : 'surface-inset'),
                color: tokenVar(active ? 'surface' : 'ink-muted'),
                ...TEXT_STYLES['figure'],
              }}
            >
              {value}
              {marked && (
                <span
                  data-testid={`step-error-${value}`}
                  title="Есть незаполненные поля"
                  style={{
                    position: 'absolute',
                    top: -3,
                    right: -3,
                    width: 8,
                    height: 8,
                    borderRadius: RADII['radius-pill'],
                    background: tokenVar('danger'),
                    border: `2px solid ${tokenVar('surface')}`,
                  }}
                />
              )}
            </span>
            <span
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar(active ? 'ink' : 'ink-muted'),
                textAlign: 'center',
              }}
            >
              {title}
            </span>
            <span
              aria-hidden="true"
              style={{
                alignSelf: 'stretch',
                height: 2,
                borderRadius: 1,
                background: tokenVar(active ? 'action' : 'line'),
                opacity: active ? 1 : 0,
              }}
            />
          </button>
        );
      })}
    </div>
  );
}
