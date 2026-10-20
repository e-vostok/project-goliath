/**
 * The edit form of PanelNationHome (UI Spec 9.6 — version 0.9.0 unit
 * 8c): the SAME tab strip and tab blocks as the registration window —
 * «РЕДАКТИРОВАНИЕ ГОСУДАРСТВА» with «ШАГ N ИЗ 4», the four tabs, one
 * `surface`/`radius-lg`/`space-4` block each, and «Отмена» /
 * «Сохранить» under the block. `CreateNationTabTerritories` renders in
 * `readOnly` mode because provinces and the capital mark never change
 * (INV-14) while the capital name does. Purely presentational: the
 * parent owns the RegistrationForm state, computes the PATCH diff
 * (`toUpdateRequest`) and performs the request.
 *
 * There is no `<form>` and no submit-on-Enter — the same keyboard rule
 * as every form: a one-line field swallows Enter, a textarea takes a
 * line break, only the explicit buttons act. Tab dots come from the
 * server field errors only — a legacy nation may be saved partially.
 */

import { useState } from 'react';
import { Button } from '@vkontakte/vkui';

import {
  BlockTitle,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import type { NationRulesDTO } from '../../../shared/types';
import type {
  NationRulesHints,
  RegistrationTabProps,
} from './CreateNationFields';
import {
  fieldToTab,
  type NationField,
  type RegistrationForm,
  type RegistrationTab,
} from './registrationForm';
import {
  CreateNationTabBar,
  CREATE_NATION_TABS,
} from './CreateNationTabBar';
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
  const [tab, setTab] = useState<RegistrationTab>(1);
  const tabProps: RegistrationTabProps = {
    form,
    rules,
    hints,
    errors,
    onFieldChange,
  };
  const tabMarks: Record<RegistrationTab, boolean> = {
    1: false,
    2: false,
    3: false,
    4: false,
  };
  for (const field of Object.keys(errors) as NationField[]) {
    tabMarks[fieldToTab(field)] = true;
  }
  const active = CREATE_NATION_TABS[tab - 1];

  return (
    <div
      data-testid="edit-nation-form"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-3'],
      }}
    >
      <BlockTitle
        icon="document"
        title="Редактирование государства"
        line={false}
        trailing={
          <span
            data-testid="step-indicator"
            style={{
              marginLeft: 'auto',
              ...TEXT_STYLES['figure'],
              color: tokenVar('ink-muted'),
            }}
          >
            Шаг {tab} из 4
          </span>
        }
      />
      <CreateNationTabBar tab={tab} onTabChange={setTab} tabMarks={tabMarks} />

      <section
        style={{
          background: tokenVar('surface'),
          borderRadius: RADII['radius-lg'],
          padding: SPACING['space-4'],
        }}
      >
        <BlockTitle icon={active.icon} title={active.title} />
        {tab === 1 && <CreateNationTabSymbols {...tabProps} />}
        {tab === 2 && <CreateNationTabLeadership {...tabProps} />}
        {tab === 3 && <CreateNationTabHistory {...tabProps} />}
        {tab === 4 && <CreateNationTabTerritories {...tabProps} readOnly />}
      </section>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        <Button
          type="button"
          mode="secondary"
          size="m"
          disabled={submitting}
          onClick={onCancel}
        >
          Отмена
        </Button>
        <span style={{ flex: '1 1 auto' }} />
        <Button
          type="button"
          size="m"
          loading={submitting}
          disabled={!canSave}
          onClick={onSubmit}
        >
          Сохранить
        </Button>
      </div>
    </div>
  );
}
