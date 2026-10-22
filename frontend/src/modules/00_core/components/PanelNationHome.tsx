/**
 * PanelNationHome — the player's own nation (Spec 1.3 Part 5, UI Spec
 * 9.1, mockup «Main», version 0.9.0 unit 8b).
 *
 * The card is built only from `shared/ui` elements and tokens: the
 * header block (flag or `FlagStub`, «ГОСУДАРСТВО · краткое», name in
 * `display-lg`, motto in italics, colour swatch + HEX, «Изменить»
 * with the pencil icon), a row of four `StatTile`s («Провинции»,
 * «Уровень», «Судейский рейтинг», «Неразрешённые приказы» — the limit
 * arrives in GET /orders/rules), «Глава государства» and «Территория»
 * in a 3 : 2 row (province chips BY NAME via `useProvinceNames`, the
 * capital first with «★»), then «Описание» with the «История
 * государства ↗» link (a real <a> only for https:// values). Gender,
 * succession, anthem and the bot-consent row are not shown on the
 * card; province numbers are shown nowhere.
 *
 * «Изменить» opens the edit form — the same tab strip and tab blocks
 * as the registration window (unit 8c): the PATCH /nations/me body
 * carries only the changed fields (`toUpdateRequest`), a cleared
 * optional field goes as an empty string, and a legacy nation may be
 * saved partially — its missing mandatory fields do not block the
 * rest; a legacy NULL flag/portrait shows the first catalog tile
 * selected, so the first save already carries its id. The bot-consent
 * row lives as one compact row at the bottom of the edit view — it was
 * reachable only from this card before.
 */

import { useEffect, useState } from 'react';
import { FormStatus } from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { useFormDraft } from '../../../shared/formDraft';
import { SUCCESS_RU } from '../../../shared/texts/success.ru';
import type { NationDTO } from '../../../shared/types';
import { SIZES, SPACING, tokenVar, useNotice } from '../../../shared/ui';
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
import { BotConsentRow } from '../../02_bot/components/BotConsentRow';
import { OrdersBlock } from '../../04_orders/components/OrdersBlock';
import { CardBlock } from './card/CardBlock';
import { NationCard } from './card/NationCard';

export interface PanelNationHomeProps {
  nation: NationDTO;
  onChanged: () => void;
}

/** Session-draft key; v1 five-field drafts under 'nation-edit:*' die out. */
const editDraftKey = (nationId: string) => `nation-edit-v2:${nationId}`;

export function PanelNationHome({
  nation,
  onChanged,
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

  // Legacy NULL flag/portrait (pre-catalog nations): the edit form
  // always shows a tile selected — the first catalog entry — so the
  // first save already carries `flag_id`/`portrait_id` even when the
  // player changed nothing else (UI Spec 9.6, unit 8c).
  useEffect(() => {
    if (!editing || rules === null) {
      return;
    }
    setForm((prev) => {
      const flagId = prev.flagId ?? rules.flags[0]?.id ?? null;
      const portraitId = prev.portraitId ?? rules.portraits[0]?.id ?? null;
      if (flagId === prev.flagId && portraitId === prev.portraitId) {
        return prev;
      }
      return { ...prev, flagId, portraitId };
    });
  }, [editing, rules]);

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

  return (
    <div
      data-testid="panel-nation-home"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-3'],
        padding: SPACING['space-4'],
        boxSizing: 'border-box',
        maxWidth: SIZES['win-screen'],
        background: tokenVar('ground'),
      }}
    >
      {editing ? (
        <div
          data-testid="nation-edit-block"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: SPACING['space-3'],
          }}
        >
          {formError && (
            <FormStatus mode="error" title="Не удалось обновить государство">
              {formError}
            </FormStatus>
          )}
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
          <CardBlock>
            <BotConsentRow />
          </CardBlock>
        </div>
      ) : (
        <NationCard nation={nation} onEdit={() => setEditing(true)} />
      )}
      <OrdersBlock />
    </div>
  );
}
