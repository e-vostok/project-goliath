/**
 * Tab 4 «Территории» of the registration window (UI Spec 9.6 —
 * version 0.9.0 unit 8c, mockup_Reg4): the line «Выбрано N из M» and
 * the «Выбрать на карте» button that opens the 01_map ProvincePicker
 * popup; under them the chosen provinces as rows with their real NAMES
 * (`useProvinceNames` resolves the ids via GET /map/province-names). The
 * capital is the first row and carries «★» in `signal-ink`; every
 * other row offers the link-button «Сделать столицей» and «×» to
 * remove the province. Below, the «Название столицы *» field with the
 * counter and the hint «По умолчанию совпадает с названием провинции».
 * Purely presentational: all state lives in the container.
 *
 * `readOnly` is the nation edit mode (INV-14): provinces and the
 * capital mark never change — the same rows render without the action
 * buttons and the picker button is gone. The capital name stays
 * editable only while the nation actually has a capital; a pre-0.8.0
 * nation (no mark) never sees the input, because the server refuses
 * `capital_name` for it.
 */

import { Button } from '@vkontakte/vkui';

import {
  FieldLabel,
  FieldMessage,
  RADII,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { useProvinceNames } from '../../01_map/hooks/useProvinceNames';
import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

export interface CreateNationTabTerritoriesProps
  extends RegistrationTabProps {
  /** Opens the map province picker modal (unused in `readOnly`). */
  onOpenPicker?: () => void;
  /** Read-only territory block of the nation edit form. */
  readOnly?: boolean;
}

export function CreateNationTabTerritories({
  form,
  rules,
  errors,
  onFieldChange,
  onOpenPicker,
  readOnly = false,
}: CreateNationTabTerritoriesProps) {
  const { names } = useProvinceNames();
  const provincesError = errors.provinces ?? errors.capitalProvinceId;
  // The marked row or, by INV-14, the first selected one. In read-only
  // mode the mark is fixed — a nation without one has no capital at all.
  const effectiveCapital =
    form.capitalProvinceId ?? (readOnly ? null : (form.provinces[0]?.value ?? null));
  // The capital row first, the rest in selection order.
  const ordered = [
    ...form.provinces.filter((chip) => chip.value === effectiveCapital),
    ...form.provinces.filter((chip) => chip.value !== effectiveCapital),
  ];
  const provinceName = (chip: { value: number; label: string }) =>
    names.get(chip.value) ?? chip.label;

  return (
    <>
      <div data-testid="form-item-provinces">
        <FieldLabel label="Провинции" required />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <span
            style={{ ...TEXT_STYLES['body'], color: tokenVar('ink-muted') }}
          >
            {rules === null
              ? `Выбрано ${form.provinces.length}`
              : `Выбрано ${form.provinces.length} из ${rules.max_provinces}`}
          </span>
          {!readOnly && (
            <Button
              mode="secondary"
              size="m"
              type="button"
              onClick={onOpenPicker}
              data-testid="open-province-picker"
            >
              Выбрать на карте
            </Button>
          )}
        </div>
        {ordered.length > 0 && (
          <div
            role="list"
            style={{
              marginTop: 8,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            {ordered.map((chip) => {
              const isCapital = chip.value === effectiveCapital;
              return (
                <div
                  key={chip.value}
                  role="listitem"
                  data-testid="province-row"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    minHeight: 32,
                    padding: '4px 8px',
                    borderRadius: RADII['radius-md'],
                    background: tokenVar('surface-inset'),
                  }}
                >
                  <span
                    style={{
                      ...TEXT_STYLES['body'],
                      color: tokenVar(isCapital ? 'signal-ink' : 'ink'),
                      flex: '1 1 auto',
                      minWidth: 0,
                    }}
                  >
                    {isCapital && (
                      <span
                        aria-hidden="true"
                        style={{ color: tokenVar('signal-ink') }}
                      >
                        {'★ '}
                      </span>
                    )}
                    {provinceName(chip)}
                  </span>
                  {!readOnly && !isCapital && (
                    <button
                      type="button"
                      onClick={() =>
                        onFieldChange('capitalProvinceId', chip.value)
                      }
                      style={{
                        border: 'none',
                        background: 'none',
                        padding: 0,
                        cursor: 'pointer',
                        ...TEXT_STYLES['caption'],
                        color: tokenVar('link'),
                      }}
                    >
                      Сделать столицей
                    </button>
                  )}
                  {!readOnly && (
                    <button
                      type="button"
                      aria-label={`Убрать ${provinceName(chip)}`}
                      onClick={() =>
                        onFieldChange(
                          'provinces',
                          form.provinces.filter(
                            (item) => item.value !== chip.value,
                          ),
                        )
                      }
                      style={{
                        border: 'none',
                        background: 'none',
                        padding: '0 4px',
                        cursor: 'pointer',
                        ...TEXT_STYLES['body'],
                        color: tokenVar('ink-muted'),
                      }}
                    >
                      ×
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
        <FieldMessage error={provincesError} />
      </div>
      {(readOnly ? form.capitalProvinceId !== null : true) && (
        <div style={{ marginTop: 16 }}>
          <CreateNationTextField
            id="nation-capital-name"
            label="Название столицы"
            required
            testId="form-item-capital-name"
            value={form.capitalName}
            maxLength={rules?.capital_name_max_length}
            error={errors.capitalName}
            hint="По умолчанию совпадает с названием провинции"
            onChange={(v) => onFieldChange('capitalName', v)}
          />
        </div>
      )}
    </>
  );
}
