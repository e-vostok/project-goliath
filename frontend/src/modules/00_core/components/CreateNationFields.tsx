/**
 * Shared primitives for the nation registration window and the nation
 * edit form:
 *
 * - `nationRulesHints` builds the Russian hint strings from the server-side
 *   NationRulesDTO (the client never hardcodes limits — hints exist only
 *   while rules are loaded).
 * - `CreateNationTextField` is one labelled FormItem + Input pair; a field
 *   error wins over the hint in `bottom`.
 * - `RegistrationTabProps` is the common prop contract of the four
 *   registration tab components: they are purely presentational and the
 *   container owns the single RegistrationForm object.
 */

import { FormItem, Input } from '@vkontakte/vkui';

import type { NationRulesDTO } from '../../../shared/types';
import type {
  NationField,
  RegistrationForm,
} from './registrationForm';

export interface NationRulesHints {
  name: string;
  shortName: string;
  motto: string;
  description: string;
  leaderName: string;
  leaderTitle: string;
  leaderBio: string;
  capitalName: string;
  historyUrl: string;
  anthemUrl: string;
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
    shortName: `от ${rules.short_name_min_length} до ${rules.short_name_max_length} символов`,
    motto: `до ${rules.motto_max_length} символов`,
    description: `до ${rules.description_max_length} символов`,
    leaderName: `от ${rules.leader_name_min_length} до ${rules.leader_name_max_length} символов`,
    leaderTitle: `от ${rules.leader_title_min_length} до ${rules.leader_title_max_length} символов`,
    leaderBio: `до ${rules.leader_bio_max_length} символов`,
    capitalName: `от ${rules.capital_name_min_length} до ${rules.capital_name_max_length} символов`,
    historyUrl:
      `до ${rules.history_url_max_length} символов. ` +
      `Допустимые домены: ${rules.history_url_allowed_hosts.join(', ')}`,
    anthemUrl:
      `до ${rules.anthem_url_max_length} символов. ` +
      `Допустимые домены: ${rules.anthem_url_allowed_hosts.join(', ')}`,
    provinces:
      rules.min_provinces === rules.max_provinces
        ? `Нужно выбрать ровно ${rules.max_provinces}`
        : `Нужно выбрать от ${rules.min_provinces} до ${rules.max_provinces}`,
  };
}

/** The prop contract shared by the four registration tab components. */
export interface RegistrationTabProps {
  form: RegistrationForm;
  rules: NationRulesDTO | null;
  hints: NationRulesHints | null;
  errors: Partial<Record<NationField, string>>;
  onFieldChange: <K extends keyof RegistrationForm>(
    field: K,
    value: RegistrationForm[K],
  ) => void;
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
