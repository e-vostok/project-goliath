/**
 * Tab 2 «Руководство» of the registration window — the fields that
 * already existed: leader name and leader title. Portrait, gender,
 * biography and the succession-type cards land with Issue 14 (their
 * values already live in the container's form). Purely presentational.
 */

import {
  CreateNationTextField,
  type RegistrationTabProps,
} from './CreateNationFields';

export function CreateNationTabLeadership({
  form,
  rules,
  hints,
  errors,
  onFieldChange,
}: RegistrationTabProps) {
  return (
    <>
      <CreateNationTextField
        id="nation-leader-name"
        label="Имя лидера"
        testId="form-item-leader-name"
        value={form.leaderName}
        maxLength={rules?.leader_name_max_length}
        error={errors.leaderName}
        hint={hints?.leaderName}
        onChange={(v) => onFieldChange('leaderName', v)}
        placeholder="напр. Иван Грозный"
      />

      <CreateNationTextField
        id="nation-leader-title"
        label="Должность лидера"
        testId="form-item-leader-title"
        value={form.leaderTitle}
        maxLength={rules?.leader_title_max_length}
        error={errors.leaderTitle}
        hint={hints?.leaderTitle}
        onChange={(v) => onFieldChange('leaderTitle', v)}
        placeholder="напр. Верховный правитель"
      />
    </>
  );
}
