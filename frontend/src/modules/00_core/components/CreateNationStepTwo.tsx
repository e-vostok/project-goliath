/**
 * Window 2 «История государства» of the create-nation wizard: the required
 * link to the nation's VK article. `hint` is the rules-driven limits text;
 * the fixed format helper is always shown alongside it until an error
 * arrives.
 */

import {
  CreateNationTextField,
  type NationRulesHints,
} from './CreateNationFields';

const HISTORY_URL_HELPER =
  'Ссылка на вашу статью ВКонтакте вида https://vk.com/@название-статьи. ' +
  'Поле обязательное.';

export interface CreateNationStepTwoProps {
  historyUrl: string;
  rules: { history_url_max_length: number } | null;
  hints: NationRulesHints | null;
  error?: string;
  onHistoryUrlChange: (value: string) => void;
}

export function CreateNationStepTwo({
  historyUrl,
  rules,
  hints,
  error,
  onHistoryUrlChange,
}: CreateNationStepTwoProps) {
  const hint = [HISTORY_URL_HELPER, hints?.historyUrl]
    .filter((part): part is string => Boolean(part))
    .join(' ');
  return (
    <CreateNationTextField
      id="nation-history-url"
      label="Ссылка на историю государства"
      testId="form-item-history-url"
      value={historyUrl}
      maxLength={rules?.history_url_max_length}
      error={error}
      hint={hint}
      onChange={onHistoryUrlChange}
      placeholder="https://vk.com/@название-статьи"
    />
  );
}
