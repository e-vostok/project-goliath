/**
 * The edit form of PanelNationHome — one form with name, color, leader
 * name, leader title and history link. Purely presentational: the parent
 * owns the values, computes the PATCH diff (`canSave`) and performs the
 * request.
 */

import {
  Button,
  ButtonGroup,
  Div,
  FormItem,
} from '@vkontakte/vkui';

import type { NationRulesDTO } from '../../../shared/types';
import {
  CreateNationTextField,
  type NationField,
  type NationRulesHints,
} from './CreateNationFields';

export type EditableNationField = Exclude<NationField, 'provinces'>;

export interface CreateNationEditFormProps {
  name: string;
  color: string;
  leaderName: string;
  leaderTitle: string;
  historyUrl: string;
  rules: NationRulesDTO | null;
  hints: NationRulesHints | null;
  errors: Partial<Record<EditableNationField, string>>;
  submitting: boolean;
  canSave: boolean;
  onTextChange: (field: EditableNationField, value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

export function CreateNationEditForm({
  name,
  color,
  leaderName,
  leaderTitle,
  historyUrl,
  rules,
  hints,
  errors,
  submitting,
  canSave,
  onTextChange,
  onSubmit,
  onCancel,
}: CreateNationEditFormProps) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      data-testid="edit-nation-form"
    >
      <CreateNationTextField
        id="edit-nation-name"
        label="Название государства"
        testId="form-item-edit-name"
        value={name}
        maxLength={rules?.name_max_length}
        error={errors.name}
        hint={hints?.name}
        onChange={(v) => onTextChange('name', v)}
      />
      <FormItem
        top="Цвет государства"
        htmlFor="edit-nation-color"
        status={errors.color ? 'error' : 'default'}
        bottom={errors.color}
        data-testid="form-item-edit-color"
      >
        <input
          id="edit-nation-color"
          type="color"
          value={color}
          onChange={(e) => onTextChange('color', e.currentTarget.value)}
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
      <CreateNationTextField
        id="edit-leader-name"
        label="Имя лидера"
        testId="form-item-edit-leader-name"
        value={leaderName}
        maxLength={rules?.leader_name_max_length}
        error={errors.leaderName}
        hint={hints?.leaderName}
        onChange={(v) => onTextChange('leaderName', v)}
      />
      <CreateNationTextField
        id="edit-leader-title"
        label="Должность лидера"
        testId="form-item-edit-leader-title"
        value={leaderTitle}
        maxLength={rules?.leader_title_max_length}
        error={errors.leaderTitle}
        hint={hints?.leaderTitle}
        onChange={(v) => onTextChange('leaderTitle', v)}
      />
      <CreateNationTextField
        id="edit-history-url"
        label="Ссылка на историю государства"
        testId="form-item-edit-history-url"
        value={historyUrl}
        maxLength={rules?.history_url_max_length}
        error={errors.historyUrl}
        hint={hints?.historyUrl}
        onChange={(v) => onTextChange('historyUrl', v)}
      />
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
