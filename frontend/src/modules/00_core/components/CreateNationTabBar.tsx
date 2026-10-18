/**
 * Tab navigation bar for the registration window: chevron IconButtons
 * («Назад»/«Вперёд»), the «Шаг N из 4» indicator and the four clickable
 * tab titles with the current one emphasized. A tab carrying a
 * field-level server error — or, once any field was edited, a missing
 * required field — while inactive is marked with a Badge; the bar never
 * switches tabs on its own. Titles wrap so the bar fits 910 px.
 */

import { Badge, Div, IconButton } from '@vkontakte/vkui';
import { Icon24ChevronLeft, Icon24ChevronRight } from '@vkontakte/icons';

import type { RegistrationTab } from './registrationForm';

export interface CreateNationTabBarProps {
  tab: RegistrationTab;
  onTabChange: (tab: RegistrationTab) => void;
  /** true when an inactive tab needs attention (error / missing field). */
  tabMarks: Record<RegistrationTab, boolean>;
}

const TAB_TITLES: Record<RegistrationTab, string> = {
  1: 'Основные данные и символика',
  2: 'Руководство',
  3: 'История и культура',
  4: 'Территории',
};

const TABS: readonly RegistrationTab[] = [1, 2, 3, 4];

export function CreateNationTabBar({
  tab,
  onTabChange,
  tabMarks,
}: CreateNationTabBarProps) {
  return (
    <Div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <IconButton
        aria-label="Назад"
        data-testid="step-prev"
        disabled={tab === 1}
        onClick={() => onTabChange((tab - 1) as RegistrationTab)}
      >
        <Icon24ChevronLeft />
      </IconButton>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div data-testid="step-indicator">Шаг {tab} из 4</div>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 8,
            alignItems: 'center',
          }}
        >
          {TABS.map((s, index) => (
            <span
              key={s}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              {index > 0 && <span aria-hidden="true">·</span>}
              <button
                type="button"
                data-testid={`step-title-${s}`}
                onClick={() => onTabChange(s)}
                style={{
                  padding: 0,
                  border: 'none',
                  background: 'none',
                  cursor: 'pointer',
                  font: 'inherit',
                  textAlign: 'left',
                  ...(tab === s
                    ? { fontWeight: 600 }
                    : { color: 'var(--vkui--color_text_secondary)' }),
                }}
              >
                {TAB_TITLES[s]}
              </button>
              {s !== tab && tabMarks[s] && (
                <Badge mode="prominent" data-testid={`step-error-${s}`} />
              )}
            </span>
          ))}
        </div>
      </div>
      <IconButton
        aria-label="Вперёд"
        data-testid="step-next"
        disabled={tab === 4}
        onClick={() => onTabChange((tab + 1) as RegistrationTab)}
      >
        <Icon24ChevronRight />
      </IconButton>
    </Div>
  );
}
