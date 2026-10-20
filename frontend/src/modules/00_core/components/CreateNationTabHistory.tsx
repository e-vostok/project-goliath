/**
 * Tab 3 «История» of the registration window (UI Spec 9.6 — version
 * 0.9.0 unit 8c): ONE field — the required link to the nation's VK
 * article. The hint names the article form and the allowed domains from
 * `GET /nations/rules` (a config change rewrites the copy). The anthem
 * link is gone from the interface entirely: no field, no form state,
 * no `anthem_url` in the request body (the server column stays unused).
 * Purely presentational.
 */

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

/** The fixed part of the hint — shown even before the rules arrive. */
const HISTORY_URL_HELPER =
  'Ссылка на вашу статью ВКонтакте вида https://vk.com/@название-статьи.';

export function CreateNationTabHistory({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  return (
    <CreateNationTextField
      id="nation-history-url"
      label="Ссылка на статью с историей государства"
      required
      testId="form-item-history-url"
      value={form.historyUrl}
      maxLength={rules?.history_url_max_length}
      error={errors.historyUrl}
      hint={hints?.historyUrl ?? HISTORY_URL_HELPER}
      onChange={(v) => onFieldChange('historyUrl', v)}
      placeholder="https://vk.com/@название-статьи"
    />
  );
}
