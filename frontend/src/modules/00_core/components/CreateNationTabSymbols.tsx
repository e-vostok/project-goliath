/**
 * Tab 1 «Основные данные и символика» of the registration window.
 * This issue ships only the fields that already existed — the nation
 * name and the color picker; short name, motto, description, the
 * palette + color-check hint and the flag catalog grid land with
 * Issues 13/14 (their values already live in the container's form).
 * Purely presentational: all state lives in PanelCreateNation.
 */

import { FormItem } from '@vkontakte/vkui';

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

export function CreateNationTabSymbols({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  return (
    <>
      <CreateNationTextField
        id="nation-name"
        label="Название государства"
        testId="form-item-name"
        value={form.name}
        maxLength={rules?.name_max_length}
        error={errors.name}
        hint={hints?.name}
        onChange={(v) => onFieldChange('name', v)}
        placeholder="напр. Северный Синдикат"
      />

      <FormItem
        top="Цвет государства"
        htmlFor="nation-color"
        status={errors.color ? 'error' : 'default'}
        bottom={errors.color}
        data-testid="form-item-color"
      >
        <input
          id="nation-color"
          type="color"
          value={form.color}
          onChange={(e) => onFieldChange('color', e.currentTarget.value)}
          style={{
            width: '100%',
            height: 36,
            padding: 0,
            border: 'none',
            background: 'none',
            cursor: 'pointer',
          }}
        />
      </FormItem>
    </>
  );
}
