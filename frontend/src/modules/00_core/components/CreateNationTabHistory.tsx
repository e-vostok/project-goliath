/**
 * Tab 3 «История и культура» of the registration window — complete in
 * this issue: the required link to the nation's VK article plus the new
 * optional anthem link. `hints` carry the rules-driven limits and
 * allowed hosts; the fixed helper lines are always shown alongside them
 * until an error arrives. Purely presentational.
 */

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

const HISTORY_URL_HELPER =
  'Ссылка на вашу статью ВКонтакте вида https://vk.com/@название-статьи. ' +
  'Поле обязательное.';

const ANTHEM_URL_HELPER =
  'Ссылка на трек или плейлист ВКонтакте; музыка внутри игры не воспроизводится.';

export function CreateNationTabHistory({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  const historyHint = [HISTORY_URL_HELPER, hints?.historyUrl]
    .filter((part): part is string => Boolean(part))
    .join(' ');
  const anthemHint = [ANTHEM_URL_HELPER, hints?.anthemUrl]
    .filter((part): part is string => Boolean(part))
    .join(' ');
  return (
    <>
      <CreateNationTextField
        id="nation-history-url"
        label="Ссылка на историю государства"
        testId="form-item-history-url"
        value={form.historyUrl}
        maxLength={rules?.history_url_max_length}
        error={errors.historyUrl}
        hint={historyHint}
        onChange={(v) => onFieldChange('historyUrl', v)}
        placeholder="https://vk.com/@название-статьи"
      />
      <CreateNationTextField
        id="nation-anthem-url"
        label="Ссылка на гимн"
        testId="form-item-anthem-url"
        value={form.anthemUrl}
        maxLength={rules?.anthem_url_max_length}
        error={errors.anthemUrl}
        hint={anthemHint}
        onChange={(v) => onFieldChange('anthemUrl', v)}
        placeholder="https://vk.com/music/playlist/..."
      />
    </>
  );
}
