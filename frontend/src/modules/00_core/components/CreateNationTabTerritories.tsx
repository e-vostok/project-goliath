/**
 * Tab 4 «Территории» of the registration window (Spec 1.3 Part 5):
 * the picked provinces as removable named chips (the capital chip
 * carries a star) plus the «Выбрать на карте» button that opens the
 * 01_map ProvincePicker modal; under the chips the «Столица: …» line
 * names the marked province — or shows that the first selected one
 * acts as the capital by default (INV-14); the capital name Input
 * auto-fills from the effective capital's province name until the
 * player edits it by hand. Purely presentational: all state lives in
 * PanelCreateNation.
 */

import { Button, Chip, Div, FormItem, Text } from '@vkontakte/vkui';
import { Icon12Star } from '@vkontakte/icons';

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

export interface CreateNationTabTerritoriesProps
  extends RegistrationTabProps {
  /** Opens the map province picker modal. */
  onOpenPicker: () => void;
}

export function CreateNationTabTerritories({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
  onOpenPicker,
}: CreateNationTabTerritoriesProps) {
  const provincesError = errors.provinces ?? errors.capitalProvinceId;
  // The marked chip or, by INV-14, the first selected one.
  const capitalChip =
    form.provinces.find((chip) => chip.value === form.capitalProvinceId) ??
    form.provinces[0];
  const capitalIsDefault = form.capitalProvinceId === null;
  return (
    <>
      <FormItem
        top="Провинции"
        status={provincesError ? 'error' : 'default'}
        bottom={provincesError ?? hints?.provinces}
        data-testid="form-item-provinces"
      >
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            alignItems: 'center',
          }}
        >
          {form.provinces.map((chip) => (
            <Chip
              key={chip.value}
              value={chip.value}
              role="option"
              before={
                chip.value === form.capitalProvinceId ? (
                  <Icon12Star aria-hidden />
                ) : undefined
              }
              onRemove={() =>
                onFieldChange(
                  'provinces',
                  form.provinces.filter((item) => item.value !== chip.value),
                )
              }
            >
              {chip.label}
            </Chip>
          ))}
          <Button
            mode="secondary"
            size="m"
            type="button"
            onClick={onOpenPicker}
            data-testid="open-province-picker"
          >
            {form.provinces.length === 0 ? 'Выбрать на карте' : 'Изменить выбор'}
          </Button>
        </div>
      </FormItem>
      {capitalChip !== undefined && (
        <Div data-testid="capital-line" style={{ paddingTop: 0 }}>
          <Text>
            Столица: {capitalChip.label}
            {capitalIsDefault ? ' (по умолчанию — первая выбранная)' : ''}
          </Text>
        </Div>
      )}
      <CreateNationTextField
        id="nation-capital-name"
        label="Название столицы"
        testId="form-item-capital-name"
        value={form.capitalName}
        maxLength={rules?.capital_name_max_length}
        error={errors.capitalName}
        hint={hints?.capitalName}
        counter
        onChange={(v) => onFieldChange('capitalName', v)}
      />
    </>
  );
}
