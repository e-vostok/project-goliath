/**
 * Tab 4 «Территории» of the registration window — the fields that
 * already existed: the picked provinces as removable named chips plus
 * the «Выбрать на карте» button that opens the 01_map ProvincePicker
 * modal. The capital marker and the capital name input land with
 * Issue 15; until then a capital error surfaces inside this FormItem.
 * Purely presentational: all state lives in PanelCreateNation.
 */

import { Button, Chip, FormItem } from '@vkontakte/vkui';

import type { RegistrationTabProps } from './CreateNationFields';

export interface CreateNationTabTerritoriesProps
  extends RegistrationTabProps {
  /** Opens the map province picker modal. */
  onOpenPicker: () => void;
}

export function CreateNationTabTerritories({
  form,
  hints,
  errors,
  onFieldChange,
  onOpenPicker,
}: CreateNationTabTerritoriesProps) {
  const provincesError =
    errors.provinces ?? errors.capitalProvinceId ?? errors.capitalName;
  return (
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
  );
}
