/**
 * ProvincesSection — «Провинции» (0.11.0 unit 9b, mockup screens
 * 04/04b/04c): transfer and withdraw a province by picking it from a
 * searchable list (never the map).
 *
 * Two columns: the left one (460 px) stacks «1. Провинция» — the
 * debounced «Поиск по названию» over GET /admin/provinces, radio rows
 * with the owner's flag stub + short name or «свободна», «Показать ещё» by
 * limit/offset — and «2. Действие» — the «Передать государству» /
 * «Вывести из-под государства» segment (withdraw is disabled for a
 * free province) plus, for a transfer, the «Государство-получатель»
 * field with suggestions from GET /admin/nations?search=&limit=8 (the
 * owner-field pattern of the nation form).
 *
 * The right card «3. Что произойдёт» is driven only by
 * GET /admin/provinces/{id}/transfer-preview — re-fetched on every
 * change of province, action or recipient, stale answers discarded by
 * a sequence counter. It shows the seize banner when `seizes`, the
 * capital banner + «Новая столица «<краткое>»» select over
 * `capital_candidates` (nothing preselected) when
 * `capital_choice_needed`, the consequence bullets with Russian
 * plurals, the seize checkbox only when `seizes`, and the bordered
 * refusal banner of 04c when `blocker` is LAST_PROVINCE (a plain one
 * for ALREADY_OWNER). The action button stays disabled until there
 * is no blocker, the recipient is chosen (for a transfer), the seize
 * box is ticked when needed and the new capital is chosen when
 * needed; POST /admin/provinces/{id}/transfer carries to_nation_id,
 * confirm_seize and new_capital_province_id. A success fires the
 * Notice, clears the selection and reloads the list; a refusal shows
 * its own line inside the card; a 401 ends the session through the
 * frame's reportUnauthorized, as everywhere.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminNationDTO,
  AdminProvinceDTO,
  AdminProvinceTransferPreviewDTO,
} from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { useNotice } from '../../../shared/ui/Notice';
import { useTheme } from '../../../shared/ui/theme';
import {
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';
import {
  PAGE_SIZE,
  SEARCH_DEBOUNCE_MS,
  SUGGEST_DEBOUNCE_MS,
  PanelButton,
  PanelCard,
  SuggestionList,
  controlStyle,
  inputStyle,
} from '../nations/shared';

const LEFT_COLUMN_WIDTH = 460;
const RECIPIENT_SUGGEST_LIMIT = 8;

const SEARCH_LABEL = 'Поиск по названию';
const RECIPIENT_LABEL = 'Государство-получатель';
const RECIPIENT_PLACEHOLDER = 'Поиск…';
const SEIZE_CHECKBOX = 'Подтверждаю изъятие провинции у другого государства';
const CAPITAL_SELECT_HINT =
  'Название столицы государства станет названием выбранной провинции.';
const PREVIEW_FOOTNOTE =
  'Если провинция — столица государства, нужно выбрать новую столицу ' +
  'из оставшихся провинций. Последнюю провинцию государства вывести ' +
  'или передать нельзя — удалите государство целиком в разделе ' +
  '«Государства».';
const JOURNAL_BULLET =
  'Запись попадёт в журнал владения карты и в журнал администратора.';

type ListStatus = 'loading' | 'ready' | 'error';
type PreviewStatus = 'idle' | 'loading' | 'ready' | 'error';
type Action = 'transfer' | 'withdraw';

/** «провинция / провинции / провинций» — the delete popup's helper. */
function provincesWord(count: number): string {
  if (count % 100 > 10 && count % 100 < 20) {
    return 'провинций';
  }
  return (
    { 1: 'провинция', 2: 'провинции', 3: 'провинции', 4: 'провинции' }[
      count % 10
    ] ?? 'провинций'
  );
}

/**
 * Approximate Russian genitive of a nation short name — the mockup
 * sentences need it («У «Лиги»», «столица «Лиги»», «провинция
 * «Союза»»). Declines only the last word: -а/-я → -ы/-и (after
 * г/к/х/ж/ш/ч/щ always -и), -ия → -ии, -ь → -и, -й → -я, a consonant
 * takes -а; endings that do not decline (-о, -е, -и, -у, -ю, -э,
 * -ё) and non-Cyrillic words stay untouched.
 */
function toGenitive(name: string): string {
  const words = name.split(' ');
  const last = words[words.length - 1];
  const lower = last.toLowerCase();
  let declined = last;
  if (lower.endsWith('ия') || lower.endsWith('ья')) {
    declined = last.slice(0, -1) + 'и';
  } else if (/[ая]$/.test(lower)) {
    const vowel = /[гкхжшчщиь]$/.test(lower.slice(0, -1)) ? 'и' : 'ы';
    declined = last.slice(0, -1) + (lower.endsWith('я') ? 'и' : vowel);
  } else if (lower.endsWith('ь')) {
    declined = last.slice(0, -1) + 'и';
  } else if (lower.endsWith('й')) {
    declined = last.slice(0, -1) + 'я';
  } else if (/[оеиуюэё]$/.test(lower) || !/[а-яА-ЯёЁ]$/.test(last)) {
    declined = last;
  } else {
    declined = `${last}а`;
  }
  words[words.length - 1] = declined;
  return words.join(' ');
}

/** Province display name — the hook-assembled name, else the bare id. */
function provinceLabel(id: number, name: string | null): string {
  return name ?? `Провинция ${id}`;
}

const captionLabel: CSSProperties = {
  ...TEXT_STYLES['caption'],
  color: tokenVar('ink-muted'),
};

/** The mockup's .fld: a normal-case caption label above the control. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}
    >
      <span style={captionLabel}>{label}</span>
      {children}
    </div>
  );
}

/** The warning triangle the mockup's .warn banner leads with. */
function WarnIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('ink')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flexShrink: 0, marginTop: 2 }}
    >
      <path d="M8 2.2l6 10.6H2z" />
      <path d="M8 6.5v3M8 11.2h.01" />
    </svg>
  );
}

/** The .warn banner; `danger` adds the 04c refusal's red frame. */
function WarnBanner({
  danger = false,
  children,
  testId,
}: {
  danger?: boolean;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        background: tokenVar('warning-bg'),
        borderRadius: RADII['radius-md'],
        padding: SPACING['space-3'],
        display: 'flex',
        gap: SPACING['space-3'],
        color: tokenVar('ink'),
        border: danger ? `1px solid ${tokenVar('danger')}` : 'none',
        ...TEXT_STYLES['body'],
      }}
    >
      <WarnIcon />
      <span>{children}</span>
    </div>
  );
}

/** One segment of the «2. Действие» switch. */
function SegmentButton({
  on,
  disabled = false,
  onClick,
  testId,
  children,
}: {
  on: boolean;
  disabled?: boolean;
  onClick: () => void;
  testId: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        height: SIZES['button-h-small'],
        padding: '0 12px',
        border: 'none',
        borderRadius: 6,
        whiteSpace: 'nowrap',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        background: on ? tokenVar('surface') : 'transparent',
        color: tokenVar(on ? 'ink' : 'ink-muted'),
        ...TEXT_STYLES['body'],
      }}
    >
      {children}
    </button>
  );
}

export function ProvincesSection() {
  const { token, reportUnauthorized } = useAdminSession();
  const notify = useNotice();
  const { resolved } = useTheme();

  /* --- card 1: the province list --- */
  const [items, setItems] = useState<AdminProvinceDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [listStatus, setListStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const listSeq = useRef(0);

  /* --- card 2: the action --- */
  const [selected, setSelected] = useState<AdminProvinceDTO | null>(null);
  const [action, setAction] = useState<Action>('transfer');
  const [recipient, setRecipient] = useState<AdminNationDTO | null>(null);
  const [recipientQuery, setRecipientQuery] = useState('');
  const [recipientSug, setRecipientSug] = useState<AdminNationDTO[]>([]);
  const [recipientOpen, setRecipientOpen] = useState(false);
  const recipientSeq = useRef(0);

  /* --- card 3: the preview --- */
  const [preview, setPreview] = useState<AdminProvinceTransferPreviewDTO | null>(
    null,
  );
  const [previewStatus, setPreviewStatus] = useState<PreviewStatus>('idle');
  const [previewError, setPreviewError] = useState<string | null>(null);
  const previewSeq = useRef(0);
  const [newCapitalId, setNewCapitalId] = useState<number | null>(null);
  const [confirmSeize, setConfirmSeize] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /* The province list — debounced search + «Показать ещё» pages. */
  const load = useCallback(
    async (searchText: string, offset: number, append: boolean) => {
      const seq = ++listSeq.current;
      try {
        const page = await api.adminProvinces(token, {
          search: searchText,
          limit: PAGE_SIZE,
          offset,
        });
        if (seq !== listSeq.current) {
          return;
        }
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
        setTotal(page.total);
        setListStatus('ready');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq !== listSeq.current) {
          return;
        }
        if (append) {
          setLoadingMore(false);
        }
        setListStatus('error');
      } finally {
        if (seq === listSeq.current) {
          setLoadingMore(false);
        }
      }
    },
    [token, reportUnauthorized],
  );

  useEffect(() => {
    const id = setTimeout(
      () => setAppliedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    setListStatus('loading');
    void load(appliedSearch, 0, false);
  }, [appliedSearch, reloadKey, load]);

  /* The preview — re-fetched on every change of province, action or
     recipient; the sequence counter discards stale answers. */
  const loadPreview = useCallback(() => {
    if (selected === null || (action === 'transfer' && recipient === null)) {
      setPreview(null);
      setPreviewStatus('idle');
      setPreviewError(null);
      return;
    }
    const seq = ++previewSeq.current;
    setPreviewStatus('loading');
    setPreviewError(null);
    api
      .adminProvinceTransferPreview(
        token,
        selected.id,
        action === 'transfer' ? recipient!.id : null,
      )
      .then((answer) => {
        if (seq === previewSeq.current) {
          setPreview(answer);
          setPreviewStatus('ready');
        }
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq === previewSeq.current) {
          setPreview(null);
          setPreviewError(errorText(error));
          setPreviewStatus('error');
        }
      });
  }, [selected, action, recipient, token, reportUnauthorized]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  /* Recipient suggestions — GET /admin/nations?search=&limit=8. */
  useEffect(() => {
    if (!recipientOpen) {
      return;
    }
    const seq = ++recipientSeq.current;
    const id = setTimeout(() => {
      api
        .adminNations(token, {
          search: recipientQuery.trim(),
          limit: RECIPIENT_SUGGEST_LIMIT,
        })
        .then((page) => {
          if (seq === recipientSeq.current) {
            setRecipientSug(page.items);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            reportUnauthorized();
          }
        });
    }, SUGGEST_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [recipientQuery, recipientOpen, token, reportUnauthorized]);

  const pickProvince = (province: AdminProvinceDTO) => {
    setSelected(province);
    setNewCapitalId(null);
    setConfirmSeize(false);
    setSubmitError(null);
    // A free province cannot leave its nation — fall back to transfer.
    if (province.nation_id === null && action === 'withdraw') {
      setAction('transfer');
    }
  };

  const pickAction = (next: Action) => {
    if (next === action) {
      return;
    }
    setAction(next);
    setNewCapitalId(null);
    setConfirmSeize(false);
    setSubmitError(null);
  };

  const pickRecipient = (nation: AdminNationDTO) => {
    setRecipient(nation);
    setRecipientQuery(nation.short_name);
    setRecipientOpen(false);
    setConfirmSeize(false);
    setSubmitError(null);
  };

  const reset = () => {
    setSelected(null);
    setAction('transfer');
    setRecipient(null);
    setRecipientQuery('');
    setRecipientOpen(false);
    setNewCapitalId(null);
    setConfirmSeize(false);
    setSubmitError(null);
  };

  const chosenCapital =
    preview !== null && newCapitalId !== null
      ? (preview.capital_candidates.find((c) => c.id === newCapitalId) ?? null)
      : null;

  const canSubmit =
    previewStatus === 'ready' &&
    preview !== null &&
    preview.blocker === null &&
    (action === 'withdraw' || recipient !== null) &&
    (!preview.seizes || confirmSeize) &&
    (!preview.capital_choice_needed || newCapitalId !== null) &&
    !busy;

  const submit = async () => {
    if (!canSubmit || preview === null || selected === null) {
      return;
    }
    setBusy(true);
    setSubmitError(null);
    try {
      await api.adminProvinceTransfer(token, selected.id, {
        to_nation_id: action === 'transfer' ? recipient!.id : null,
        confirm_seize: confirmSeize,
        new_capital_province_id: preview.capital_choice_needed
          ? newCapitalId
          : null,
      });
      const provinceName = provinceLabel(
        preview.province.id,
        preview.province.name,
      );
      if (action === 'transfer') {
        notify(
          `Провинция «${provinceName}» передана государству ` +
            `«${recipient!.short_name}».`,
        );
      } else {
        notify(
          `Провинция «${provinceName}» выведена из-под государства ` +
            `«${preview.from_nation!.short_name}».`,
        );
      }
      reset();
      setReloadKey((key) => key + 1);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The refusal lands inside the card — the selection stays.
      setSubmitError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const canWithdraw = selected !== null && selected.nation_id !== null;
  const donorGen =
    preview?.from_nation !== null && preview?.from_nation !== undefined
      ? toGenitive(preview.from_nation.short_name)
      : null;

  const bullets = (() => {
    if (preview === null) {
      return [];
    }
    const lines: string[] = [];
    if (preview.to_nation !== null && preview.receiver_after !== null) {
      lines.push(
        `«${preview.to_nation.short_name}» получит ещё одну провинцию: ` +
          `станет ${preview.receiver_after}.`,
      );
    } else {
      lines.push('Провинция станет свободной.');
    }
    if (preview.from_nation !== null && preview.donor_after !== null) {
      let capitalTail = '';
      if (preview.capital_choice_needed) {
        if (chosenCapital !== null) {
          capitalTail = `, столица — ${provinceLabel(
            chosenCapital.id,
            chosenCapital.name,
          )}`;
        }
      } else if (preview.from_nation.capital_name !== null) {
        capitalTail = `, столица (${preview.from_nation.capital_name}) ` +
          'на месте';
      }
      lines.push(
        `У «${donorGen}» останется ${preview.donor_after} ` +
          `${provincesWord(preview.donor_after)}${capitalTail}.`,
      );
    }
    lines.push(JOURNAL_BULLET);
    return lines;
  })();

  const onAction = tokenVar(resolved === 'dark' ? 'ground' : 'surface');

  return (
    <>
      <h1
        style={{
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          ...TEXT_STYLES['title-uppercase'],
          fontSize: 24,
          lineHeight: '28px',
        }}
      >
        <PanelIcon name="pin" accent size={20} />
        Провинции
      </h1>

      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
        {/* Left column — the mockup's fixed 460 px. */}
        <div
          data-testid="provinces-left-column"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            width: LEFT_COLUMN_WIDTH,
            flexShrink: 0,
          }}
        >
          <PanelCard title="1. Провинция">
            <Field label={SEARCH_LABEL}>
              <input
                data-testid="province-search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                  }
                }}
                style={inputStyle}
              />
            </Field>
            {listStatus === 'loading' && <LoadingState height={120} />}
            {listStatus === 'error' && (
              <ErrorState
                onRetry={() => {
                  setListStatus('loading');
                  void load(appliedSearch, 0, false);
                }}
              />
            )}
            {listStatus === 'ready' && items.length === 0 && (
              <EmptyState
                text={
                  appliedSearch === ''
                    ? 'Провинций пока нет.'
                    : 'Ничего не нашлось по этому запросу.'
                }
              />
            )}
            {listStatus === 'ready' && items.length > 0 && (
              <div
                data-testid="province-list"
                style={{
                  border: `1px solid ${tokenVar('line')}`,
                  borderRadius: RADII['radius-md'],
                  overflow: 'hidden',
                }}
              >
                {items.map((province, index) => {
                  const isSelected = selected?.id === province.id;
                  return (
                    <button
                      key={province.id}
                      type="button"
                      data-testid={`province-row-${province.id}`}
                      onClick={() => pickProvince(province)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: SPACING['space-3'],
                        width: '100%',
                        minHeight: 44,
                        padding: '4px 12px',
                        border: 'none',
                        borderBottom:
                          index < items.length - 1
                            ? `1px solid ${tokenVar('line')}`
                            : 'none',
                        borderRadius: isSelected ? RADII['radius-md'] : 0,
                        background: isSelected
                          ? tokenVar('surface-inset')
                          : 'transparent',
                        color: tokenVar('ink'),
                        cursor: 'pointer',
                        textAlign: 'left',
                        ...TEXT_STYLES['body'],
                      }}
                    >
                      <span
                        aria-hidden="true"
                        style={{
                          width: 16,
                          height: 16,
                          flexShrink: 0,
                          boxSizing: 'border-box',
                          borderRadius: 999,
                          border: `2px solid ${tokenVar(
                            isSelected ? 'action' : 'ink-faint',
                          )}`,
                          background: isSelected
                            ? `radial-gradient(circle, ${tokenVar('action')} ` +
                              '40%, transparent 45%)'
                            : 'none',
                        }}
                      />
                      <span
                        style={{
                          flexGrow: 1,
                          minWidth: 0,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {provinceLabel(province.id, province.name)}
                      </span>
                      {province.nation_id === null ? (
                        <span
                          style={{
                            ...TEXT_STYLES['caption'],
                            color: tokenVar('ink-muted'),
                          }}
                        >
                          свободна
                        </span>
                      ) : (
                        <span
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: SPACING['space-2'],
                          }}
                        >
                          <span
                            aria-hidden="true"
                            style={{
                              display: 'block',
                              width: 18,
                              height: 12,
                              flexShrink: 0,
                              borderRadius: RADII['radius-sm'],
                              background: tokenVar('surface-inset'),
                            }}
                          />
                          <span
                            style={{
                              ...TEXT_STYLES['caption'],
                              color: tokenVar('ink'),
                            }}
                          >
                            {province.nation_short_name ?? ''}
                          </span>
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            )}
            {listStatus === 'ready' && items.length < total && (
              <div style={{ display: 'flex', justifyContent: 'center' }}>
                <PanelButton
                  testId="provinces-load-more"
                  disabled={loadingMore}
                  onClick={() => {
                    setLoadingMore(true);
                    void load(appliedSearch, items.length, true);
                  }}
                >
                  Показать ещё
                </PanelButton>
              </div>
            )}
          </PanelCard>

          <PanelCard title="2. Действие">
            <div
              style={{
                display: 'inline-flex',
                alignSelf: 'flex-start',
                gap: 4,
                background: tokenVar('surface-inset'),
                borderRadius: RADII['radius-md'],
                padding: 2,
              }}
            >
              <SegmentButton
                on={action === 'transfer'}
                testId="action-transfer"
                onClick={() => pickAction('transfer')}
              >
                Передать государству
              </SegmentButton>
              <SegmentButton
                on={action === 'withdraw'}
                disabled={!canWithdraw}
                testId="action-withdraw"
                onClick={() => pickAction('withdraw')}
              >
                Вывести из-под государства
              </SegmentButton>
            </div>
            {action === 'transfer' && (
              <div style={{ position: 'relative' }}>
                <Field label={RECIPIENT_LABEL}>
                  <input
                    data-testid="recipient-input"
                    value={recipientQuery}
                    placeholder={RECIPIENT_PLACEHOLDER}
                    onChange={(event) => {
                      setRecipientQuery(event.currentTarget.value);
                      setRecipient(null);
                      setRecipientOpen(true);
                    }}
                    onFocus={() => setRecipientOpen(true)}
                    onBlur={() => setRecipientOpen(false)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                      }
                    }}
                    style={inputStyle}
                  />
                </Field>
                {recipientOpen && (
                  <SuggestionList
                    items={recipientSug.map((nation) => (
                      <span key={nation.id}>
                        {nation.short_name}
                        <span
                          style={{
                            color: tokenVar('ink-muted'),
                            marginLeft: 8,
                          }}
                        >
                          {nation.name}
                        </span>
                      </span>
                    ))}
                    onPick={(index) => pickRecipient(recipientSug[index])}
                    optionTestId={(index) => `recipient-option-${index}`}
                  />
                )}
              </div>
            )}
          </PanelCard>
        </div>

        {/* Right column — the consequences card. */}
        <div style={{ flexGrow: 1, minWidth: 0 }}>
          <PanelCard title="3. Что произойдёт">
            {selected === null && (
              <EmptyState text="Выберите провинцию слева — здесь появится, что произойдёт." />
            )}
            {selected !== null &&
              action === 'transfer' &&
              recipient === null && (
                <EmptyState text="Выберите государство-получатель — здесь появится, что произойдёт." />
              )}
            {previewStatus === 'loading' && <LoadingState height={160} />}
            {previewStatus === 'error' && (
              <ErrorState
                reason={previewError ?? undefined}
                onRetry={loadPreview}
              />
            )}
            {previewStatus === 'ready' && preview !== null && (
              <>
                {preview.blocker === 'LAST_PROVINCE' && (
                  <WarnBanner danger testId="preview-blocker">
                    <b style={{ fontWeight: 500 }}>
                      {`Это последняя провинция «${donorGen}».`}
                    </b>
                    {
                      ' Вывести или передать её нельзя: государство без ' +
                        'провинций не бывает. Если государство больше не ' +
                        'нужно, удалите его целиком в разделе «Государства».'
                    }
                  </WarnBanner>
                )}
                {preview.blocker === 'ALREADY_OWNER' && (
                  <WarnBanner testId="preview-blocker">
                    Провинция уже принадлежит этому государству.
                  </WarnBanner>
                )}
                {preview.blocker === null && (
                  <>
                    {preview.seizes && preview.from_nation !== null && (
                      <WarnBanner testId="preview-seize-banner">
                        <b style={{ fontWeight: 500 }}>
                          Провинция занята другим государством.
                        </b>
                        {` «${provinceLabel(
                          preview.province.id,
                          preview.province.name,
                        )}» сейчас принадлежит государству «${
                          preview.from_nation.short_name
                        }» и будет у него изъята.`}
                      </WarnBanner>
                    )}
                    {preview.capital_choice_needed &&
                      preview.from_nation !== null && (
                        <>
                          <WarnBanner testId="preview-capital-banner">
                            <b style={{ fontWeight: 500 }}>
                              {`«${provinceLabel(
                                preview.province.id,
                                preview.province.name,
                              )}» — столица «${donorGen}».`}
                            </b>
                            {
                              ' Выберите новую столицу из оставшихся провинций.'
                            }
                          </WarnBanner>
                          <Field label={`Новая столица «${donorGen}»`}>
                            <select
                              data-testid="capital-select"
                              value={newCapitalId ?? ''}
                              onChange={(event) => {
                                const value = event.currentTarget.value;
                                setNewCapitalId(
                                  value === '' ? null : Number(value),
                                );
                              }}
                              style={{ ...controlStyle, width: '100%' }}
                            >
                              <option value="" disabled>
                                Выберите…
                              </option>
                              {preview.capital_candidates.map((candidate) => (
                                <option
                                  key={candidate.id}
                                  value={candidate.id}
                                >
                                  {provinceLabel(candidate.id, candidate.name)}
                                </option>
                              ))}
                            </select>
                            <span style={captionLabel}>
                              {CAPITAL_SELECT_HINT}
                            </span>
                          </Field>
                        </>
                      )}
                    <ul
                      data-testid="preview-bullets"
                      style={{
                        margin: 0,
                        paddingLeft: 20,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 4,
                      }}
                    >
                      {bullets.map((line) => (
                        <li key={line} style={TEXT_STYLES['body']}>
                          {line}
                        </li>
                      ))}
                    </ul>
                    {preview.seizes && (
                      <button
                        type="button"
                        role="checkbox"
                        aria-checked={confirmSeize}
                        data-testid="seize-confirm"
                        onClick={() => setConfirmSeize((value) => !value)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: SPACING['space-3'],
                          border: 'none',
                          background: 'transparent',
                          padding: 0,
                          cursor: 'pointer',
                          color: tokenVar('ink'),
                          textAlign: 'left',
                          ...TEXT_STYLES['body'],
                        }}
                      >
                        <span
                          aria-hidden="true"
                          style={{
                            width: 18,
                            height: 18,
                            flexShrink: 0,
                            boxSizing: 'border-box',
                            borderRadius: RADII['radius-sm'],
                            border: `2px solid ${tokenVar(
                              confirmSeize ? 'action' : 'ink-faint',
                            )}`,
                            background: confirmSeize
                              ? tokenVar('action')
                              : 'transparent',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                          }}
                        >
                          {confirmSeize && (
                            <svg
                              width={11}
                              height={11}
                              viewBox="0 0 12 12"
                              fill="none"
                              stroke={onAction}
                              strokeWidth={2}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            >
                              <path d="M2 6.5l2.8 2.8L10 3.5" />
                            </svg>
                          )}
                        </span>
                        <span style={{ flexGrow: 1 }}>{SEIZE_CHECKBOX}</span>
                      </button>
                    )}
                  </>
                )}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    gap: SPACING['space-3'],
                  }}
                >
                  <PanelButton
                    testId="province-cancel"
                    disabled={busy}
                    onClick={reset}
                  >
                    Отмена
                  </PanelButton>
                  <PanelButton
                    kind="primary"
                    testId="province-submit"
                    disabled={!canSubmit}
                    onClick={() => void submit()}
                  >
                    {action === 'transfer'
                      ? 'Передать провинцию'
                      : 'Вывести провинцию'}
                  </PanelButton>
                </div>
                {submitError !== null && (
                  <span
                    data-testid="preview-error"
                    style={{
                      ...TEXT_STYLES['caption'],
                      color: tokenVar('danger'),
                    }}
                  >
                    {submitError}
                  </span>
                )}
                {preview.blocker === null &&
                  !preview.capital_choice_needed && (
                    <span
                      data-testid="preview-footnote"
                      style={captionLabel}
                    >
                      {PREVIEW_FOOTNOTE}
                    </span>
                  )}
              </>
            )}
          </PanelCard>
        </div>
      </div>
    </>
  );
}
