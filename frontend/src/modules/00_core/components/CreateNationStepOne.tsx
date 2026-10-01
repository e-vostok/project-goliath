/**
 * Window 1 «Основная информация» of the create-nation wizard: name, color,
 * provinces (ChipsInput with numeric-only entry) and the leader fields.
 * Purely presentational — all state lives in PanelCreateNation, so
 * switching windows loses nothing and sends nothing.
 */

import { ChipsInput, FormItem } from '@vkontakte/vkui';

import type { NationRulesDTO } from '../../../shared/types';
import {
  CreateNationTextField,
  type NationField,
  type NationRulesHints,
} from './CreateNationFields';

export interface ChipOption {
  value: number;
  label: string;
}

export interface CreateNationStepOneProps {
  name: string;
  color: string;
  chips: ChipOption[];
  chipsInput: string;
  leaderName: string;
  leaderTitle: string;
  rules: NationRulesDTO | null;
  hints: NationRulesHints | null;
  errors: Partial<Record<NationField, string>>;
  /** Free-IDs hint plus the server province-count range, joined. */
  provincesHint?: string;
  onNameChange: (value: string) => void;
  onColorChange: (value: string) => void;
  onChipsChange: (chips: ChipOption[]) => void;
  onChipsInputChange: (value: string) => void;
  onLeaderNameChange: (value: string) => void;
  onLeaderTitleChange: (value: string) => void;
}

export function CreateNationStepOne({
  name,
  color,
  chips,
  chipsInput,
  leaderName,
  leaderTitle,
  rules,
  hints,
  errors,
  provincesHint,
  onNameChange,
  onColorChange,
  onChipsChange,
  onChipsInputChange,
  onLeaderNameChange,
  onLeaderTitleChange,
}: CreateNationStepOneProps) {
  return (
    <>
      <CreateNationTextField
        id="nation-name"
        label="Название государства"
        testId="form-item-name"
        value={name}
        maxLength={rules?.name_max_length}
        error={errors.name}
        hint={hints?.name}
        onChange={onNameChange}
        placeholder="напр. Северный Синдикат"
      />

      <FormItem
        top="Цвет государства"
        htmlFor="nation-color"
        status={errors.color ? 'error' : 'default'}
        bottom={errors.color}
        data-testid="form-item-color"
      >
        <input
          id="nation-color"
          type="color"
          value={color}
          onChange={(e) => onColorChange(e.currentTarget.value)}
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

      <FormItem
        top="Провинции"
        status={errors.provinces ? 'error' : 'default'}
        bottom={errors.provinces ?? provincesHint}
        data-testid="form-item-provinces"
      >
        <ChipsInput
          value={chips}
          inputValue={chipsInput}
          placeholder="Введите ID провинции и нажмите Enter"
          onInputChange={(e) =>
            onChipsInputChange(e.currentTarget.value.replace(/\D/g, ''))
          }
          onChange={onChipsChange}
          getNewOptionData={(_, label) => ({
            value: Number(label),
            label: String(label),
          })}
          addOnBlur
        />
      </FormItem>

      <CreateNationTextField
        id="nation-leader-name"
        label="Имя лидера"
        testId="form-item-leader-name"
        value={leaderName}
        maxLength={rules?.leader_name_max_length}
        error={errors.leaderName}
        hint={hints?.leaderName}
        onChange={onLeaderNameChange}
        placeholder="напр. Иван Грозный"
      />

      <CreateNationTextField
        id="nation-leader-title"
        label="Должность лидера"
        testId="form-item-leader-title"
        value={leaderTitle}
        maxLength={rules?.leader_title_max_length}
        error={errors.leaderTitle}
        hint={hints?.leaderTitle}
        onChange={onLeaderTitleChange}
        placeholder="напр. Верховный правитель"
      />
    </>
  );
}
