/**
 * Step navigation bar for the PanelCreateNation wizard: chevron
 * IconButtons («Назад»/«Вперёд»), the «Шаг n из 2» indicator and both
 * window titles with the current one emphasized. A step carrying a
 * field-level server error while inactive is marked with a Badge; the bar
 * never switches windows on its own.
 */

import { Badge, Div, IconButton } from '@vkontakte/vkui';
import { Icon24ChevronLeft, Icon24ChevronRight } from '@vkontakte/icons';

export interface CreateNationStepBarProps {
  step: 1 | 2;
  onStepChange: (step: 1 | 2) => void;
  /** true when a field on that step currently carries a server error. */
  stepErrors: Record<1 | 2, boolean>;
}

const STEP_TITLES: Record<1 | 2, string> = {
  1: 'Основная информация',
  2: 'История государства',
};

export function CreateNationStepBar({
  step,
  onStepChange,
  stepErrors,
}: CreateNationStepBarProps) {
  return (
    <Div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <IconButton
        aria-label="Назад"
        data-testid="step-prev"
        disabled={step === 1}
        onClick={() => onStepChange(1)}
      >
        <Icon24ChevronLeft />
      </IconButton>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div data-testid="step-indicator">Шаг {step} из 2</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {([1, 2] as const).map((s, index) => (
            <span
              key={s}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
            >
              {index > 0 && <span aria-hidden="true">·</span>}
              <span
                data-testid={`step-title-${s}`}
                style={
                  step === s
                    ? { fontWeight: 600 }
                    : { color: 'var(--vkui--color_text_secondary)' }
                }
              >
                {STEP_TITLES[s]}
              </span>
              {s !== step && stepErrors[s] && (
                <Badge mode="prominent" data-testid={`step-error-${s}`} />
              )}
            </span>
          ))}
        </div>
      </div>
      <IconButton
        aria-label="Вперёд"
        data-testid="step-next"
        disabled={step === 2}
        onClick={() => onStepChange(2)}
      >
        <Icon24ChevronRight />
      </IconButton>
    </Div>
  );
}
