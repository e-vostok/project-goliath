/**
 * PanelNationHome — the player's existing nation (Spec 1.3 Part 5).
 *
 * The card shows every nation field: flag and portrait images (only
 * when set — a missing catalog picture leaves no broken icon), full and
 * short names, motto and description (only when present), the color
 * swatch, the province list, the capital line («название (провинция
 * N)», hidden while the nation has no capital), leader name, gender,
 * title and biography, the succession method with the «Пока без
 * последствий» caption, and the history/anthem links rendered as real
 * <a target="_blank" rel="noopener noreferrer"> only when the stored
 * value starts with "https://" — anything else is plain text (defense
 * in depth; the server remains the validator). A field that is null on
 * a pre-0.8.0 nation shows «не указано» — except the optional ones,
 * which are simply hidden.
 *
 * «Изменить» opens one form built from the same tab components as the
 * registration window (provinces and the capital mark stay read-only);
 * the PATCH /nations/me body carries only the changed fields
 * (`toUpdateRequest`), a cleared optional field goes as an empty
 * string, and a legacy nation may be saved partially — its missing
 * mandatory fields do not block the rest.
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
import { errorText } from '../../../shared/errorTexts';
import { useFormDraft } from '../../../shared/formDraft';
import { SUCCESS_RU } from '../../../shared/texts/success.ru';
import type { GameClockDTO, NationDTO } from '../../../shared/types';
import { useNotice } from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { nationRulesHints } from './CreateNationFields';
import { CreateNationEditForm } from './CreateNationEditForm';
import {
  isValidColorHex,
  mapErrorCodeToField,
  registrationFormFromDraft,
  registrationFormFromNation,
  toUpdateRequest,
  type NationField,
  type RegistrationForm,
} from './registrationForm';
import { GENDER_LABELS, SUCCESSION_LABELS } from './nationLabels';
import { BotConsentRow } from '../../02_bot/components/BotConsentRow';
import { OrdersBlock } from '../../04_orders/components/OrdersBlock';

export interface PanelNationHomeProps {
  nation: NationDTO;
  onChanged: () => void;
  onDeleteRequest: () => void;
}

/** Session-draft key; v1 five-field drafts under 'nation-edit:*' die out. */
const editDraftKey = (nationId: string) => `nation-edit-v2:${nationId}`;

/** Only https values become real links — anything else is plain text. */
function externalLink(url: string, label: string) {
  return url.startsWith('https://') ? (
    <Link href={url} target="_blank" rel="noopener noreferrer">
      {label}
    </Link>
  ) : (
    url
  );
}

export function PanelNationHome({
  nation,
  onChanged,
  onDeleteRequest,
}: PanelNationHomeProps) {
  const { token } = useSession();
  const notify = useNotice();
  const rulesState = useNationRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;
  const hints = nationRulesHints(rules);

  // Draft memory, keyed by nation — reopening the edit form restores
  // the typed values; «Отмена» and a successful save delete it.
  const {
    draft: storedDraft,
    setDraft: setStoredDraft,
    clearDraft,
  } = useFormDraft<RegistrationForm>(editDraftKey(nation.id));

  const [clock, setClock] = useState<GameClockDTO | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<RegistrationForm>(() => {
    const seed = registrationFormFromNation(nation);
    return storedDraft === null
      ? seed
      : registrationFormFromDraft({ ...seed, ...storedDraft });
  });
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<NationField, string>>
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

  // PATCH body — only fields whose normalized value actually changed.
  const changes = toUpdateRequest(form, nation);

  // While the form is open, mirror it into the session draft; a form
  // identical to the nation's own values means nothing is pending.
  useEffect(() => {
    if (!editing) {
      return;
    }
    if (Object.keys(toUpdateRequest(form, nation)).length === 0) {
      clearDraft();
    } else {
      setStoredDraft(form);
    }
  }, [editing, form, nation, setStoredDraft, clearDraft]);

  // A mandatory field the nation already has must not be emptied;
  // legacy (null) fields may stay empty — the nation can be edited
  // without filling them (Spec 1.3: partial legacy edits allowed).
  const filledNowEmpty = (stored: string | null, edited: string) =>
    stored !== null && stored !== '' && edited.trim() === '';
  const emptiedFilledField =
    filledNowEmpty(nation.name, form.name) ||
    filledNowEmpty(nation.short_name, form.shortName) ||
    filledNowEmpty(nation.leader_name, form.leaderName) ||
    filledNowEmpty(nation.gender, form.gender) ||
    filledNowEmpty(nation.leader_title, form.leaderTitle) ||
    filledNowEmpty(nation.succession_type, form.successionType) ||
    filledNowEmpty(nation.history_url, form.historyUrl) ||
    filledNowEmpty(nation.capital_name, form.capitalName);

  const canSave =
    Object.keys(changes).length > 0 &&
    form.name.trim().length >= (rules?.name_min_length ?? 1) &&
    isValidColorHex(form.color) &&
    !emptiedFilledField &&
    !submitting;

  const clearFieldError = (field: NationField) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });

  const handleFieldChange = <K extends keyof RegistrationForm>(
    field: K,
    value: RegistrationForm[K],
  ) => {
    setForm((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'capitalName') {
        // A hand-typed name is never auto-overwritten again.
        next.capitalNameEdited = true;
      }
      return next;
    });
    clearFieldError(field);
  };

  const handleSave = async () => {
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      await api.updateNation(token, changes);
      clearDraft();
      setEditing(false);
      notify(SUCCESS_RU.nationSaved);
      onChanged();
    } catch (error) {
      if (error instanceof ApiError) {
        const field = mapErrorCodeToField(error.code);
        if (field) {
          setFieldErrors({
            [field]: errorText(error, { rules }),
          });
        } else {
          setFormError(errorText(error));
        }
      } else {
        setFormError(errorText(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const resetEdit = () => {
    clearDraft();
    setEditing(false);
    setForm(registrationFormFromNation(nation));
    setFieldErrors({});
    setFormError(null);
  };

  const headerText = clock
    ? `Ход ${clock.current_turn} · ${clock.game_date_text}`
    : 'Ваше государство';

  const succession = nation.succession_type;
  const gender = nation.gender;

  return (
    <>
      <PanelHeader>{nation.name}</PanelHeader>
      <Group header={<Header size="l">{headerText}</Header>}>
        {(nation.flag_url || nation.portrait_url) && (
          <Div
            style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}
          >
            {nation.flag_url && (
              <img
                src={nation.flag_url}
                alt={`Флаг ${nation.name}`}
                width={96}
                height={64}
                style={{ borderRadius: 6, objectFit: 'cover' }}
              />
            )}
            {nation.portrait_url && (
              <img
                src={nation.portrait_url}
                alt={`Портрет лидера ${nation.name}`}
                width={96}
                height={128}
                style={{ borderRadius: 6, objectFit: 'cover' }}
              />
            )}
          </Div>
        )}
        <SimpleCell disabled subtitle="Название" multiline>
          {nation.name}
        </SimpleCell>
        <SimpleCell disabled subtitle="Краткое название" multiline>
          {nation.short_name || 'не указано'}
        </SimpleCell>
        {nation.motto && (
          <SimpleCell disabled subtitle="Девиз" multiline>
            {nation.motto}
          </SimpleCell>
        )}
        {nation.description && (
          <SimpleCell disabled subtitle="Описание" multiline>
            {nation.description}
          </SimpleCell>
        )}
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
        <SimpleCell disabled subtitle="Провинции" multiline>
          {nation.province_ids.length > 0
            ? nation.province_ids.join(', ')
            : 'Нет'}
        </SimpleCell>
        {nation.capital_province_id !== null && (
          <SimpleCell disabled subtitle="Столица" multiline>
            {nation.capital_name || 'не указано'} (провинция{' '}
            {nation.capital_province_id})
          </SimpleCell>
        )}
        <SimpleCell disabled subtitle="Лидер" multiline>
          {nation.leader_name || 'не указано'}
        </SimpleCell>
        <SimpleCell disabled subtitle="Пол">
          {(gender && (GENDER_LABELS[gender] ?? gender)) || 'не указано'}
        </SimpleCell>
        <SimpleCell disabled subtitle="Должность" multiline>
          {nation.leader_title || 'не указано'}
        </SimpleCell>
        {nation.leader_bio && (
          <SimpleCell disabled subtitle="Биография лидера" multiline>
            {nation.leader_bio}
          </SimpleCell>
        )}
        <SimpleCell
          disabled
          subtitle="Способ смены лидера"
          extraSubtitle="Пока без последствий в игре"
          multiline
        >
          {(succession &&
            (SUCCESSION_LABELS[succession]?.title ?? succession)) ||
            'не указано'}
        </SimpleCell>
        <SimpleCell disabled subtitle="История государства" multiline>
          {nation.history_url
            ? externalLink(nation.history_url, 'Открыть статью')
            : 'не указано'}
        </SimpleCell>
        {nation.anthem_url && (
          <SimpleCell disabled subtitle="Гимн" multiline>
            {externalLink(nation.anthem_url, 'Слушать гимн')}
          </SimpleCell>
        )}
        <BotConsentRow />

        {formError && (
          <FormStatus mode="error" title="Не удалось обновить государство">
            {formError}
          </FormStatus>
        )}

        {editing ? (
          <CreateNationEditForm
            form={form}
            rules={rules}
            hints={hints}
            errors={fieldErrors}
            submitting={submitting}
            canSave={canSave}
            onFieldChange={handleFieldChange}
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
      <OrdersBlock />
    </>
  );
}
