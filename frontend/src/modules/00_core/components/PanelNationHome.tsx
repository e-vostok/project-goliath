/**
 * PanelNationHome — the player's existing nation.
 *
 * Group with a Header showing turn number + game date (GET /game-clock),
 * SimpleCell rows for name / color swatch / province IDs / leader name /
 * leader title / history link, plus edit (PATCH /nations/me — only changed
 * fields are sent) and destructive delete buttons.
 *
 * The history link is rendered as a real <a target="_blank"> only when the
 * stored value starts with "https://" — anything else is plain text
 * (defense in depth; the server remains the validator). Legacy nations
 * created before the profile fields show «не указано» and may be renamed
 * without filling the profile.
 */

import { useEffect, useState } from 'react';
import {
  Button,
  ButtonGroup,
  Div,
  FormStatus,
  Group,
  Header,
  Link,
  PanelHeader,
  SimpleCell,
} from '@vkontakte/vkui';
import { Icon24Write, Icon24Delete } from '@vkontakte/icons';

import { api, ApiError } from '../../../shared/api-client';
import type {
  GameClockDTO,
  NationDTO,
  NationUpdateRequest,
} from '../../../shared/types';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { nationRulesHints } from './CreateNationFields';
import {
  CreateNationEditForm,
  type EditableNationField,
} from './CreateNationEditForm';
import { mapErrorCodeToField } from './PanelCreateNation';

export interface PanelNationHomeProps {
  nation: NationDTO;
  onChanged: () => void;
  onDeleteRequest: () => void;
}

export function PanelNationHome({
  nation,
  onChanged,
  onDeleteRequest,
}: PanelNationHomeProps) {
  const { token } = useSession();
  const rulesState = useNationRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;
  const hints = nationRulesHints(rules);

  const [clock, setClock] = useState<GameClockDTO | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(nation.name);
  const [editColor, setEditColor] = useState(nation.color_hex);
  const [editLeaderName, setEditLeaderName] = useState(nation.leader_name ?? '');
  const [editLeaderTitle, setEditLeaderTitle] = useState(
    nation.leader_title ?? '',
  );
  const [editHistoryUrl, setEditHistoryUrl] = useState(nation.history_url ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<EditableNationField, string>>
  >({});
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getGameClock(token, controller.signal)
      .then(setClock)
      .catch(() => {});
    return () => controller.abort();
  }, [token]);

  const trimmed = {
    name: editName.trim(),
    leaderName: editLeaderName.trim(),
    leaderTitle: editLeaderTitle.trim(),
    historyUrl: editHistoryUrl.trim(),
  };

  // PATCH body — only fields whose trimmed value actually changed.
  const changes: NationUpdateRequest = {};
  if (trimmed.name !== nation.name) {
    changes.name = trimmed.name;
  }
  if (editColor !== nation.color_hex) {
    changes.color_hex = editColor;
  }
  if (trimmed.leaderName !== (nation.leader_name ?? '')) {
    changes.leader_name = trimmed.leaderName;
  }
  if (trimmed.leaderTitle !== (nation.leader_title ?? '')) {
    changes.leader_title = trimmed.leaderTitle;
  }
  if (trimmed.historyUrl !== (nation.history_url ?? '')) {
    changes.history_url = trimmed.historyUrl;
  }

  // A field the nation already has must not be emptied; legacy (null)
  // fields may stay empty — the nation can be renamed without them.
  const emptiedFilledField =
    (nation.leader_name !== null &&
      nation.leader_name !== '' &&
      trimmed.leaderName === '') ||
    (nation.leader_title !== null &&
      nation.leader_title !== '' &&
      trimmed.leaderTitle === '') ||
    (nation.history_url !== null &&
      nation.history_url !== '' &&
      trimmed.historyUrl === '');

  const canSave =
    Object.keys(changes).length > 0 &&
    trimmed.name.length >= (rules?.name_min_length ?? 1) &&
    !emptiedFilledField &&
    !submitting;

  const clearFieldError = (field: EditableNationField) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });

  const editSetters: Record<EditableNationField, (v: string) => void> = {
    name: setEditName,
    color: setEditColor,
    leaderName: setEditLeaderName,
    leaderTitle: setEditLeaderTitle,
    historyUrl: setEditHistoryUrl,
  };
  const handleEditChange = (field: EditableNationField, value: string) => {
    editSetters[field](value);
    clearFieldError(field);
  };

  const handleSave = async () => {
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      await api.updateNation(token, changes);
      setEditing(false);
      onChanged();
    } catch (error) {
      if (error instanceof ApiError) {
        const field = mapErrorCodeToField(error.code);
        if (field && field !== 'provinces') {
          setFieldErrors({ [field]: error.message });
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError('Ошибка сети — попробуйте ещё раз.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const resetEdit = () => {
    setEditing(false);
    setEditName(nation.name);
    setEditColor(nation.color_hex);
    setEditLeaderName(nation.leader_name ?? '');
    setEditLeaderTitle(nation.leader_title ?? '');
    setEditHistoryUrl(nation.history_url ?? '');
    setFieldErrors({});
    setFormError(null);
  };

  const history = nation.history_url;
  const historyCell = !history ? (
    'не указано'
  ) : history.startsWith('https://') ? (
    <Link href={history} target="_blank" rel="noopener noreferrer">
      Открыть статью
    </Link>
  ) : (
    history
  );

  const headerText = clock
    ? `Ход ${clock.current_turn} · ${clock.game_date}`
    : 'Ваше государство';

  return (
    <>
      <PanelHeader>{nation.name}</PanelHeader>
      <Group header={<Header size="l">{headerText}</Header>}>
        <SimpleCell disabled subtitle="Название">
          {nation.name}
        </SimpleCell>
        <SimpleCell
          disabled
          subtitle="Цвет"
          before={
            <div
              aria-label={`Цвет ${nation.color_hex}`}
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                background: nation.color_hex,
                border: '1px solid rgba(0,0,0,0.15)',
              }}
            />
          }
        >
          {nation.color_hex}
        </SimpleCell>
        <SimpleCell disabled subtitle="Провинции">
          {nation.province_ids.length > 0
            ? nation.province_ids.join(', ')
            : 'Нет'}
        </SimpleCell>
        <SimpleCell disabled subtitle="Лидер">
          {nation.leader_name || 'не указано'}
        </SimpleCell>
        <SimpleCell disabled subtitle="Должность">
          {nation.leader_title || 'не указано'}
        </SimpleCell>
        <SimpleCell disabled subtitle="История государства">
          {historyCell}
        </SimpleCell>

        {formError && (
          <FormStatus mode="error" title="Не удалось обновить государство">
            {formError}
          </FormStatus>
        )}

        {editing ? (
          <CreateNationEditForm
            name={editName}
            color={editColor}
            leaderName={editLeaderName}
            leaderTitle={editLeaderTitle}
            historyUrl={editHistoryUrl}
            rules={rules}
            hints={hints}
            errors={fieldErrors}
            submitting={submitting}
            canSave={canSave}
            onTextChange={handleEditChange}
            onSubmit={handleSave}
            onCancel={resetEdit}
          />
        ) : (
          <Div>
            <ButtonGroup stretched>
              <Button
                size="l"
                stretched
                mode="secondary"
                before={<Icon24Write />}
                onClick={() => setEditing(true)}
              >
                Изменить
              </Button>
              <Button
                size="l"
                stretched
                mode="primary"
                appearance="negative"
                before={<Icon24Delete />}
                onClick={onDeleteRequest}
              >
                Удалить
              </Button>
            </ButtonGroup>
          </Div>
        )}
      </Group>
    </>
  );
}
