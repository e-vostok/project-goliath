/**
 * Field helpers of the registration window — thin adapters over the
 * shared `TextField`/`TextArea` set (UI Spec 9.6 — version 0.9.0 unit
 * 8c):
 *
 * - `nationRulesHints` builds the one rules-driven hint (the history
 *   link's allowed domains) so a config change rewrites the UI copy.
 *   Length hints are gone: the «N / M» counter in the label row says
 *   the limit — a second «до N символов» under a field is forbidden.
 * - `CreateNationTextField` / `CreateNationTextArea` keep the form's
 *   plumbing (label, `required` star, limits from `rules`, the field
 *   error slot) while every pixel — label row, `surface-inset` input,
 *   danger error with a mark — comes from the shared kit.
 * - `RegistrationTabProps` is the common prop contract of the four
 *   registration tab components: they are purely presentational and the
 *   container owns the single RegistrationForm object.
 *
 * The word «необязательно» is never written: a field without «*» is
 * optional by itself.
 */

import { Icon16Done } from '@vkontakte/icons';

import { RADII, TextArea, TextField, tokenVar } from '../../../shared/ui';

import type { NationRulesDTO } from '../../../shared/types';
import type {
  NationField,
  RegistrationForm,
} from './registrationForm';

/** Hint strings per field; null while rules are unavailable (loading/error). */
export interface NationRulesHints {
  /** Domains hint under the history link — the one rules-driven hint. */
  historyUrl: string;
}

export function nationRulesHints(
  rules: NationRulesDTO | null,
): NationRulesHints | null {
  if (!rules) {
    return null;
  }
  return {
    historyUrl:
      'Ссылка на вашу статью ВКонтакте вида ' +
      'https://vk.com/@название-статьи. Допустимые домены: ' +
      rules.history_url_allowed_hosts.join(', '),
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
  /** Required fields carry the «*» after the label name. */
  required?: boolean;
  /** The label row shows the «N / M» counter while a limit is known. */
  maxLength?: number;
  error?: string;
  hint?: string;
  testId?: string;
  onChange: (value: string) => void;
}

/** The selection badge on a picked tile/card: a check mark, not color alone. */
export function PickCheck() {
  return (
    <span
      aria-hidden="true"
      style={{
        position: 'absolute',
        top: 4,
        right: 4,
        width: 20,
        height: 20,
        borderRadius: RADII['radius-pill'],
        background: tokenVar('action'),
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Icon16Done width={12} height={12} style={{ color: '#FFFFFF' }} />
    </span>
  );
}

export function CreateNationTextField({
  id,
  label,
  value,
  placeholder,
  required = false,
  maxLength,
  error,
  hint,
  testId,
  onChange,
}: CreateNationTextFieldProps) {
  return (
    <TextField
      id={id}
      label={label}
      value={value}
      placeholder={placeholder}
      required={required}
      maxLength={maxLength}
      error={error}
      hint={hint}
      testId={testId}
      onChange={onChange}
    />
  );
}

export function CreateNationTextArea({
  id,
  label,
  value,
  placeholder,
  required = false,
  maxLength,
  error,
  hint,
  rows = 2,
  testId,
  onChange,
}: CreateNationTextFieldProps & { rows?: number }) {
  return (
    <TextArea
      id={id}
      label={label}
      value={value}
      placeholder={placeholder}
      required={required}
      maxLength={maxLength}
      error={error}
      hint={hint}
      rows={rows}
      testId={testId}
      onChange={onChange}
    />
  );
}
