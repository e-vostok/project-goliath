/**
 * The edit form of PanelNationHome (Spec 1.3 Part 5): the same inputs
 * as the registration window — the four tab components are reused
 * verbatim, `CreateNationTabTerritories` in `readOnly` mode, because
 * provinces and the capital mark never change (INV-14) while the
 * capital name does. Purely presentational: the parent owns the
 * RegistrationForm state, computes the PATCH diff (`toUpdateRequest`)
 * and performs the request.
 */

import { Button, ButtonGroup, Div } from '@vkontakte/vkui';

import type { NationRulesDTO } from '../../../shared/types';
import type { NationRulesHints, RegistrationTabProps } from './CreateNationFields';
import type { NationField, RegistrationForm } from './registrationForm';
import { CreateNationTabSymbols } from './CreateNationTabSymbols';
import { CreateNationTabLeadership } from './CreateNationTabLeadership';
import { CreateNationTabHistory } from './CreateNationTabHistory';
import { CreateNationTabTerritories } from './CreateNationTabTerritories';

export interface CreateNationEditFormProps {
  form: RegistrationForm;
  rules: NationRulesDTO | null;
  hints: NationRulesHints | null;
  errors: Partial<Record<NationField, string>>;
  submitting: boolean;
  canSave: boolean;
  onFieldChange: RegistrationTabProps['onFieldChange'];
  onSubmit: () => void;
  onCancel: () => void;
}

export function CreateNationEditForm({
  form,
  rules,
  hints,
  errors,
  submitting,
  canSave,
  onFieldChange,
  onSubmit,
  onCancel,
}: CreateNationEditFormProps) {
  const tabProps: RegistrationTabProps = {
    form,
    rules,
    hints,
    errors,
    onFieldChange,
  };
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      data-testid="edit-nation-form"
    >
      <CreateNationTabSymbols {...tabProps} />
      <CreateNationTabLeadership {...tabProps} />
      <CreateNationTabHistory {...tabProps} />
      <CreateNationTabTerritories {...tabProps} readOnly />
      <Div>
        <ButtonGroup stretched>
          <Button
            type="submit"
            size="l"
            stretched
            loading={submitting}
            disabled={!canSave}
          >
            Сохранить
          </Button>
          <Button
            type="button"
            size="l"
            stretched
            mode="secondary"
            disabled={submitting}
            onClick={onCancel}
          >
            Отмена
          </Button>
        </ButtonGroup>
      </Div>
    </form>
  );
}
