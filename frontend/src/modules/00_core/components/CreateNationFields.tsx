/**
 * Shared primitives for the nation create wizard and the nation edit form:
 *
 * - `nationRulesHints` builds the Russian hint strings from the server-side
 *   NationRulesDTO (the client never hardcodes limits — hints exist only
 *   while rules are loaded).
 * - `CreateNationTextField` is one labelled FormItem + Input pair; a field
 *   error wins over the hint in `bottom`.
 */

import { FormItem, Input } from '@vkontakte/vkui';

import type { NationRulesDTO } from '../../../shared/types';

/** Field keys shared by the create wizard and the edit form error mapping. */
export type NationField =
  | 'name'
  | 'color'
  | 'provinces'
  | 'leaderName'
  | 'leaderTitle'
  | 'historyUrl';

export interface NationRulesHints {
  name: string;
  leaderName: string;
  leaderTitle: string;
  historyUrl: string;
  provinces: string;
}

/** Hint strings per field; null while rules are unavailable (loading/error). */
export function nationRulesHints(
  rules: NationRulesDTO | null,
): NationRulesHints | null {
  if (!rules) {
    return null;
  }
  return {
    name: `от ${rules.name_min_length} до ${rules.name_max_length} символов`,
    leaderName: `от ${rules.leader_name_min_length} до ${rules.leader_name_max_length} символов`,
    leaderTitle: `от ${rules.leader_title_min_length} до ${rules.leader_title_max_length} символов`,
    historyUrl:
      `до ${rules.history_url_max_length} символов. ` +
      `Допустимые домены: ${rules.history_url_allowed_hosts.join(', ')}`,
    provinces: `Нужно выбрать от ${rules.min_provinces} до ${rules.max_provinces}`,
  };
}

export interface CreateNationTextFieldProps {
  id: string;
  label: string;
  value: string;
  placeholder?: string;
  maxLength?: number;
  error?: string;
  hint?: string;
  testId?: string;
  onChange: (value: string) => void;
}

export function CreateNationTextField({
  id,
  label,
  value,
  placeholder,
  maxLength,
  error,
  hint,
  testId,
  onChange,
}: CreateNationTextFieldProps) {
  return (
    <FormItem
      top={label}
      htmlFor={id}
      status={error ? 'error' : 'default'}
      bottom={error ?? hint}
      data-testid={testId}
    >
      <Input
        id={id}
        value={value}
        maxLength={maxLength}
        onChange={(e) => onChange(e.currentTarget.value)}
        placeholder={placeholder}
      />
    </FormItem>
  );
}
