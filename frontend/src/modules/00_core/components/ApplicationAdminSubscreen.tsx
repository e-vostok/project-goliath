/**
 * ApplicationAdminSubscreen — the administrator's application window
 * (Spec applications §10, mockups 21/21b/21c/21d of version 0.13.0):
 * the subscreen the bot's `#application/<id>` link opens in the Mini
 * App, kept in the «Штаб» panel in the same shell pattern as the
 * nation subscreen. Address: `#/application/<id>`.
 *
 * The facts card holds the review facts (applicant, send time with
 * the submission number, decision deadline with the remaining time)
 * while the
 * application is PENDING; decided or withdrawn applications show the
 * state line of mockup 21d instead — and an administrator reading
 * their OWN application gets the «свою анкету рассматривать нельзя»
 * note with the decision buttons hidden (APP-3).
 *
 * «Удалить флаг»/«Удалить портрет» ask in an S popup, then call the
 * image delete; «Вернуть с причиной» opens the M dialog of 21b
 * (comment up to `application.comment_max_length` from
 * GET /nations/rules, the button stays off while it is empty);
 * «Принять анкету» confirms in the S popup of 21c. A decision or a
 * delete refused with 409/403 reloads the window and shows the new
 * state — never a stacked error.
 */

import { useEffect, useRef, useState } from 'react';
import { Button, FormStatus, Link } from '@vkontakte/vkui';
import { Icon16ArrowLeftOutline } from '@vkontakte/icons';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { ErrorCodes } from '../../../shared/types';
import type {
  AdminApplicationDTO,
  NationPublicDTO,
} from '../../../shared/types';
import {
  BlockTitle,
  EmptyState,
  ErrorState,
  FONTS,
  LoadingState,
  Popup,
  RADII,
  SPACING,
  Subscreen,
  TextArea,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { useNationRules } from '../hooks/useNationRules';
import { DangerOutlineButton } from './DangerOutlineButton';
import { CardBlock, CARD_BLOCK_STYLE } from './card/CardBlock';
import { LeaderBlock } from './card/LeaderBlock';
import { NationCardHeader } from './card/NationCardHeader';
import {
  applicationAsNation,
  ApplicationTerritory,
} from './PanelApplication';

/**
 * Dates in the facts card render like the mockup — «31 октября,
 * 14:20» in the tick timezone (Europe/Moscow, 00_core.yaml
 * `tick_timezone`, the zone PanelApplication hardcodes too).
 */
const factDateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  timeZone: 'Europe/Moscow',
});
const factTimeFmt = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Europe/Moscow',
});

/** «31 октября, 14:20» — no zone suffix in the admin window (21). */
function formatFactDateTime(iso: string): string {
  const date = new Date(iso);
  return `${factDateFmt.format(date)}, ${factTimeFmt.format(date)}`;
}

/** Russian plural: pluralRu(24, 'час', 'часа', 'часов') → 'часов'. */
function pluralRu(n: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(n) % 100;
  const mod10 = mod100 % 10;
  if (mod100 > 10 && mod100 < 20) {
    return many;
  }
  if (mod10 > 1 && mod10 < 5) {
    return few;
  }
  if (mod10 === 1) {
    return one;
  }
  return many;
}

/** «осталось 21 ч 40 мин» of mockup 21; «срок вышел» once past. */
function remainingText(deadlineIso: string, nowMs: number): string {
  const left = new Date(deadlineIso).getTime() - nowMs;
  if (left <= 0) {
    return 'срок вышел';
  }
  const totalMin = Math.floor(left / 60_000);
  const days = Math.floor(totalMin / 1440);
  const hours = Math.floor((totalMin % 1440) / 60);
  const mins = totalMin % 60;
  if (days > 0) {
    return `осталось ${days} д ${hours} ч`;
  }
  if (hours > 0) {
    return mins > 0
      ? `осталось ${hours} ч ${mins} мин`
      : `осталось ${hours} ч`;
  }
  return `осталось ${mins} мин`;
}

/** «(один раз возвращалась)» — the resubmission note of mockup 21. */
function returnedTimesText(count: number): string {
  if (count === 1) {
    return 'один раз возвращалась';
  }
  if (count === 2) {
    return 'два раза возвращалась';
  }
  return `${count} ${pluralRu(count, 'раз', 'раза', 'раз')} возвращалась`;
}

/** The clock glyph of the «На рассмотрении» pill — 14 px stroke. */
function ClockGlyph() {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.5V8l2.5 1.5" />
    </svg>
  );
}

/** Popup-title glyphs of mockups 21b/21c — 18 px, signal-ink stroke. */
function ReturnGlyph() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z" />
    </svg>
  );
}

function ShieldGlyph() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d="M8 1.8l5 1.8v4.2c0 3-2.2 5-5 6.4-2.8-1.4-5-3.4-5-6.4V3.6z" />
      <path d="M5.8 8l1.7 1.7L10.5 6.4" />
    </svg>
  );
}

/**
 * The state pill of the facts card (mockups 21/21d): «На
 * рассмотрении» in amber, «Принята»/«Принята автоматически» in
 * positive, «Возвращена» in danger, «Отозвана игроком» neutral.
 */
function StatusPill({
  application,
}: {
  application: AdminApplicationDTO;
}) {
  let text = 'Черновик';
  let color = tokenVar('ink');
  let background = tokenVar('surface-inset');
  let clock = false;
  if (application.status === 'PENDING') {
    text = 'На рассмотрении';
    color = tokenVar('signal-ink');
    background = tokenVar('warning-bg');
    clock = true;
  } else if (application.status === 'ACCEPTED') {
    text = application.auto_accepted === true
      ? 'Принята автоматически'
      : 'Принята';
    color = tokenVar('positive');
  } else if (
    application.draft_reason === 'returned' ||
    application.draft_reason === 'failed'
  ) {
    text = 'Возвращена';
    color = tokenVar('danger');
  } else if (application.draft_reason === 'cancelled') {
    text = 'Отозвана игроком';
  }
  return (
    <span
      data-testid="application-admin-state"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        flexShrink: 0,
        ...TEXT_STYLES['caption'],
        padding: '2px 10px',
        borderRadius: RADII['radius-pill'],
        background,
        color,
      }}
    >
      {clock && <ClockGlyph />}
      {text}
    </span>
  );
}

/** The «Игрок … · отправка №N» facts grid of mockup 21 (PENDING). */
function PendingFacts({
  application,
}: {
  application: AdminApplicationDTO;
}) {
  const ownerLine =
    application.owner_name ??
    (application.owner_vk_user_id !== null
      ? `id ${application.owner_vk_user_id}`
      : '—');
  return (
    <>
      <div
        style={{
          marginTop: SPACING['space-3'],
          display: 'grid',
          gridTemplateColumns: '150px 1fr',
          gap: `6px ${SPACING['space-3']}px`,
          ...TEXT_STYLES['body'],
          color: tokenVar('ink'),
        }}
      >
        <span style={{ color: tokenVar('ink-muted') }}>Игрок</span>
        <span>
          {ownerLine}
          {application.owner_vk_user_id !== null &&
            application.owner_name !== null && (
              <span
                style={{
                  ...TEXT_STYLES['caption'],
                  fontFamily: FONTS.mono,
                  color: tokenVar('ink-muted'),
                }}
              >
                {` · id ${application.owner_vk_user_id}`}
              </span>
            )}
        </span>
        <span style={{ color: tokenVar('ink-muted') }}>Отправлена</span>
        <span>
          {application.submitted_at !== null
            ? formatFactDateTime(application.submitted_at)
            : '—'}
          <span
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            {` · отправка №${application.submissions}`}
            {application.submissions > 1 &&
              ` (${returnedTimesText(application.submissions - 1)})`}
          </span>
        </span>
        <span style={{ color: tokenVar('ink-muted') }}>Решение до</span>
        <span>
          {application.review_deadline_at !== null ? (
            <>
              {formatFactDateTime(application.review_deadline_at)}
              <span
                style={{
                  ...TEXT_STYLES['caption'],
                  color: tokenVar('ink-muted'),
                }}
              >
                {` · ${remainingText(
                  application.review_deadline_at,
                  Date.now(),
                )}`}
              </span>
            </>
          ) : (
            '—'
          )}
        </span>
      </div>
      <div
        style={{
          ...TEXT_STYLES['caption'],
          color: tokenVar('ink-muted'),
          marginTop: 10,
        }}
      >
        Если решения не будет до срока, анкета примется автоматически
        «как есть». Картинки можно удалить до решения.
      </div>
    </>
  );
}

/**
 * The one-line state of mockup 21d — withdrawn, accepted, auto-
 * accepted, returned or the reader's own application. The server DTO
 * carries no decider name and no return/cancel stamp, so the lines
 * name only what it sends (the mockup's «Анна Кузнецова» and the
 * cancel time have no source).
 */
function stateLine(
  application: AdminApplicationDTO,
  isOwn: boolean,
  reviewHours: number | null,
): string {
  if (application.status === 'PENDING' && isOwn) {
    return (
      'Свою анкету рассматривать нельзя. Её решит другой ' +
      'администратор или она примется автоматически.'
    );
  }
  if (application.status === 'ACCEPTED') {
    const when =
      application.decided_at !== null
        ? ` ${formatFactDateTime(application.decided_at)}`
        : '';
    if (application.auto_accepted === true) {
      return reviewHours !== null
        ? `Решения не было ${reviewHours} ${pluralRu(
            reviewHours,
            'час',
            'часа',
            'часов',
          )}, анкета принята «как есть»${when}.`
        : `Анкета принята «как есть»${when}.`;
    }
    return `Анкета принята${when}. Государство создано.`;
  }
  if (application.draft_reason === 'cancelled') {
    return (
      'Игрок отменил анкету. Решать нечего: кнопки «Принять» и ' +
      '«Вернуть» скрыты.'
    );
  }
  if (application.draft_reason === 'returned') {
    return `Анкету вернул администратор: «${application.return_comment ?? ''}»`;
  }
  if (application.draft_reason === 'failed') {
    return `Анкета возвращена автоматически: «${application.return_comment ?? ''}»`;
  }
  return 'Анкета ещё не отправлена — игрок заполняет черновик.';
}

/** The facts card's body — the PENDING grid or the 21d state line. */
function FactsCard({
  application,
  isOwn,
  reviewHours,
}: {
  application: AdminApplicationDTO;
  isOwn: boolean;
  reviewHours: number | null;
}) {
  const pending = application.status === 'PENDING' && !isOwn;
  return (
    <CardBlock testId="application-admin-facts">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: SPACING['space-3'],
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              ...TEXT_STYLES['label'],
              color: tokenVar('ink-muted'),
            }}
          >
            Анкета государства
          </div>
          <div
            style={{
              ...TEXT_STYLES['heading'],
              fontSize: 20,
              lineHeight: '24px',
              color: tokenVar('ink'),
              marginTop: 2,
            }}
          >
            {application.name}
          </div>
        </div>
        <StatusPill application={application} />
      </div>
      {pending ? (
        <PendingFacts application={application} />
      ) : (
        <div
          style={{
            ...TEXT_STYLES['body'],
            color: tokenVar('ink'),
            marginTop: SPACING['space-2'],
          }}
        >
          {stateLine(application, isOwn, reviewHours)}
        </div>
      )}
    </CardBlock>
  );
}

type LoadState =
  | { status: 'loading' }
  | { status: 'ready'; application: AdminApplicationDTO }
  | { status: 'notfound' }
  | { status: 'error'; error: unknown };

export function ApplicationAdminSubscreen({
  applicationId,
  onBack,
}: {
  /** The application UUID — the `/application/:sub` route segment. */
  applicationId: string;
  /**
   * «← Штаб» and the silent fallback: a 403 (not an administrator)
   * lands on the plain default panel with no error shown.
   */
  onBack: () => void;
}) {
  const { token, player } = useSession();
  const rulesState = useNationRules();
  const commentMax =
    rulesState.status === 'ready'
      ? rulesState.rules.application.comment_max_length
      : undefined;
  const reviewHours =
    rulesState.status === 'ready'
      ? rulesState.rules.application.review_hours
      : null;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [busy, setBusy] = useState(false);
  const [returnOpen, setReturnOpen] = useState(false);
  const [comment, setComment] = useState('');
  const [returnError, setReturnError] = useState<string | null>(null);
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [deleteKind, setDeleteKind] = useState<'flag' | 'portrait' | null>(
    null,
  );
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const onBackRef = useRef(onBack);
  onBackRef.current = onBack;

  useEffect(() => {
    let alive = true;
    setState({ status: 'loading' });
    api
      .adminApplication(token, applicationId)
      .then((application) => {
        if (alive) {
          setState({ status: 'ready', application });
        }
      })
      .catch((error: unknown) => {
        if (!alive) {
          return;
        }
        // A non-administrator gets the plain default panel — the
        // server's 403 is swallowed, no error is shown (TZ 7b).
        if (error instanceof ApiError && error.status === 403) {
          onBackRef.current();
          return;
        }
        setState(
          error instanceof ApiError &&
            (error.status === 404 ||
              error.code === ErrorCodes.APPLICATION_NOT_FOUND)
            ? { status: 'notfound' }
            : { status: 'error', error },
        );
      });
    return () => {
      alive = false;
    };
  }, [token, applicationId, attempt]);

  const application =
    state.status === 'ready' ? state.application : null;
  const nation: NationPublicDTO | null =
    application !== null ? applicationAsNation(application) : null;
  const isOwn =
    application !== null &&
    application.owner_vk_user_id !== null &&
    application.owner_vk_user_id === player.vk_user_id;
  const live =
    application !== null &&
    (application.status === 'PENDING' || application.status === 'DRAFT');
  const canDecide = application !== null && application.status === 'PENDING' && !isOwn;

  /**
   * A refused decision or delete (409 — somebody else decided first,
   * 403 — it turned out to be the reader's own application) silently
   * reloads the window: the new state plate is the answer (APP-3).
   */
  const isRaceError = (error: unknown): boolean =>
    error instanceof ApiError &&
    (error.code === ErrorCodes.APPLICATION_NOT_PENDING ||
      error.code === ErrorCodes.APPLICATION_SELF_REVIEW);

  const doAccept = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setAcceptError(null);
    try {
      const answer = await api.adminAcceptApplication(token, applicationId);
      setAcceptOpen(false);
      setState({ status: 'ready', application: answer });
    } catch (error) {
      if (isRaceError(error)) {
        setAcceptOpen(false);
        setAttempt((n) => n + 1);
      } else {
        setAcceptError(errorText(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const doReturn = async () => {
    if (busy || comment.trim() === '') {
      return;
    }
    setBusy(true);
    setReturnError(null);
    try {
      const answer = await api.adminReturnApplication(
        token,
        applicationId,
        comment.trim(),
      );
      setReturnOpen(false);
      setComment('');
      setState({ status: 'ready', application: answer });
    } catch (error) {
      if (isRaceError(error)) {
        setReturnOpen(false);
        setComment('');
        setAttempt((n) => n + 1);
      } else {
        setReturnError(errorText(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const doDeleteImage = async () => {
    if (busy || deleteKind === null) {
      return;
    }
    const kind = deleteKind;
    setBusy(true);
    setDeleteError(null);
    try {
      const answer = await api.adminApplicationImageDelete(
        token,
        applicationId,
        kind,
      );
      setDeleteKind(null);
      setState({ status: 'ready', application: answer });
    } catch (error) {
      // A picture already gone (404) or a decision that landed first
      // — reload; the window shows what is actually there.
      if (
        isRaceError(error) ||
        (error instanceof ApiError && error.status === 404)
      ) {
        setDeleteKind(null);
        setAttempt((n) => n + 1);
      } else {
        setDeleteError(errorText(error));
      }
    } finally {
      setBusy(false);
    }
  };

  const trail =
    application === null
      ? ['Анкеты']
      : ['Анкеты', application.name];
  const provincesCount = application?.provinces.length ?? 0;
  const imageLine = (() => {
    const flag = application?.images.flag != null;
    const portrait = application?.images.portrait != null;
    if (flag && portrait) {
      return 'Флаг и портрет перейдут государству.';
    }
    if (flag) {
      return 'Флаг перейдёт государству.';
    }
    if (portrait) {
      return 'Портрет перейдёт государству.';
    }
    return null;
  })();

  return (
    <Subscreen parentLabel="Штаб" trail={trail} onBack={onBack}>
      {state.status === 'loading' && <LoadingState height={200} />}

      {state.status === 'error' && (
        <ErrorState
          reason={errorText(state.error)}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}

      {state.status === 'notfound' && (
        <EmptyState
          text="Анкета не найдена"
          action={
            <Button
              size="s"
              mode="secondary"
              before={<Icon16ArrowLeftOutline width={16} height={16} />}
              onClick={onBack}
              aria-label="← Штаб"
            >
              Штаб
            </Button>
          }
        />
      )}

      {application !== null && nation !== null && (
        <div
          data-testid="application-admin"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: SPACING['space-3'],
          }}
        >
          <FactsCard
            application={application}
            isOwn={isOwn}
            reviewHours={reviewHours}
          />

          <NationCardHeader
            nation={nation}
            action={
              live && application.images.flag !== null ? (
                <DangerOutlineButton
                  small
                  testId="delete-flag"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteKind('flag');
                  }}
                >
                  Удалить флаг
                </DangerOutlineButton>
              ) : undefined
            }
          />

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '3fr 2fr',
              gap: SPACING['space-3'],
              alignItems: 'start',
            }}
          >
            <LeaderBlock
              nation={nation}
              action={
                live && application.images.portrait !== null ? (
                  <DangerOutlineButton
                    small
                    testId="delete-portrait"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleteKind('portrait');
                    }}
                  >
                    Удалить портрет
                  </DangerOutlineButton>
                ) : undefined
              }
            />
            <ApplicationTerritory application={application} />
          </div>

          {application.description !== null &&
            application.description !== '' && (
              <CardBlock testId="application-description-block">
                <BlockTitle icon="text" title="Описание" />
                <div
                  style={{
                    ...TEXT_STYLES['body'],
                    color: tokenVar('ink'),
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {application.description}
                </div>
              </CardBlock>
            )}

          {application.history_url !== null &&
            application.history_url !== '' && (
              <CardBlock testId="application-history-block">
                <BlockTitle icon="document" title="История" />
                <div style={{ ...TEXT_STYLES['body'] }}>
                  {application.history_url.startsWith('https://') ? (
                    <Link
                      href={application.history_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        color: tokenVar('link'),
                        overflowWrap: 'anywhere',
                      }}
                    >
                      {application.history_url} ↗
                    </Link>
                  ) : (
                    <span style={{ color: tokenVar('ink-muted') }}>
                      {application.history_url}
                    </span>
                  )}
                </div>
              </CardBlock>
            )}

          {canDecide && (
            <section
              data-testid="application-admin-actions"
              style={{
                ...CARD_BLOCK_STYLE,
                position: 'sticky',
                bottom: 0,
                display: 'flex',
                alignItems: 'center',
                gap: SPACING['space-3'],
              }}
            >
              <DangerOutlineButton
                testId="open-return-application"
                onClick={() => {
                  setComment('');
                  setReturnError(null);
                  setReturnOpen(true);
                }}
              >
                Вернуть с причиной
              </DangerOutlineButton>
              <span style={{ flex: 1 }} />
              <span
                style={{
                  ...TEXT_STYLES['caption'],
                  color: tokenVar('ink-muted'),
                }}
              >
                Свою анкету рассматривать нельзя.
              </span>
              <Button
                mode="primary"
                size="m"
                data-testid="open-accept-application"
                onClick={() => {
                  setAcceptError(null);
                  setAcceptOpen(true);
                }}
              >
                Принять анкету
              </Button>
            </section>
          )}

          {returnOpen && (
            <Popup
              size="M"
              /* The mockup's title carries a signal-ink glyph before
                 the text — Popup draws only BlockIcons before the
                 title, so the pair rides `headerExtra` and the title
                 string itself stays empty. */
              title=""
              headerExtra={
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: SPACING['space-2'],
                    marginLeft: -SPACING['space-2'],
                  }}
                >
                  <ReturnGlyph />
                  Вернуть анкету
                </span>
              }
              onClose={() => setReturnOpen(false)}
              testId="popup-return-application"
              footer={
                <>
                  <Button
                    size="m"
                    mode="secondary"
                    disabled={busy}
                    onClick={() => setReturnOpen(false)}
                  >
                    Отмена
                  </Button>
                  <Button
                    size="m"
                    mode="primary"
                    loading={busy}
                    disabled={comment.trim() === ''}
                    data-testid="confirm-return-application"
                    onClick={() => void doReturn()}
                  >
                    Вернуть анкету
                  </Button>
                </>
              }
            >
              <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink') }}>
                Игрок получит вашу причину в сообщении сообщества и
                сможет исправить анкету. Закрепление провинций, цвета и
                названий будет снято.
              </div>
              <TextArea
                id="application-return-comment"
                label="Причина возврата"
                required
                value={comment}
                maxLength={commentMax}
                rows={4}
                error={returnError ?? undefined}
                testId="return-comment"
                onChange={(value) => {
                  setComment(value);
                  setReturnError(null);
                }}
              />
            </Popup>
          )}

          {acceptOpen && (
            <Popup
              size="S"
              title=""
              headerExtra={
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: SPACING['space-2'],
                    marginLeft: -SPACING['space-2'],
                  }}
                >
                  <ShieldGlyph />
                  Принять анкету?
                </span>
              }
              onClose={() => setAcceptOpen(false)}
              testId="popup-accept-application"
              footer={
                <>
                  <Button
                    size="m"
                    mode="secondary"
                    disabled={busy}
                    onClick={() => setAcceptOpen(false)}
                  >
                    Отмена
                  </Button>
                  <Button
                    size="m"
                    mode="primary"
                    loading={busy}
                    data-testid="confirm-accept-application"
                    onClick={() => void doAccept()}
                  >
                    Принять анкету
                  </Button>
                </>
              }
            >
              <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink') }}>
                Будет создано государство «{application.name}».
              </div>
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 20,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                  ...TEXT_STYLES['body'],
                  color: tokenVar('ink'),
                }}
              >
                <li>
                  {`${provincesCount} ${pluralRu(
                    provincesCount,
                    'провинция',
                    'провинции',
                    'провинций',
                  )} ${
                    provincesCount === 1 ? 'закрепится' : 'закрепятся'
                  } за ним, столица — ${application.capital_name ?? '—'}.`}
                </li>
                {imageLine !== null && <li>{imageLine}</li>}
                <li>Игрок получит сообщение и сможет открыть «Штаб».</li>
              </ul>
              <div
                style={{
                  ...TEXT_STYLES['caption'],
                  color: tokenVar('ink-muted'),
                }}
              >
                Решение записывается в журнал администратора.
              </div>
              {acceptError !== null && (
                <FormStatus mode="error" title="Не удалось принять анкету">
                  {acceptError}
                </FormStatus>
              )}
            </Popup>
          )}

          {deleteKind !== null && (
            <Popup
              size="S"
              title={
                deleteKind === 'flag' ? 'Удалить флаг?' : 'Удалить портрет?'
              }
              onClose={() => setDeleteKind(null)}
              testId="popup-delete-image"
              footer={
                <>
                  <Button
                    size="m"
                    mode="secondary"
                    disabled={busy}
                    onClick={() => setDeleteKind(null)}
                  >
                    Отмена
                  </Button>
                  <Button
                    size="m"
                    appearance="negative"
                    loading={busy}
                    data-testid="confirm-delete-image"
                    onClick={() => void doDeleteImage()}
                  >
                    {deleteKind === 'flag'
                      ? 'Удалить флаг'
                      : 'Удалить портрет'}
                  </Button>
                </>
              }
            >
              <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink') }}>
                Картинка будет удалена из анкеты «{application.name}».
                Вернуть её нельзя — игроку придётся загрузить новую.
              </div>
              <div
                style={{
                  ...TEXT_STYLES['caption'],
                  color: tokenVar('ink-muted'),
                }}
              >
                Действие записывается в журнал администратора.
              </div>
              {deleteError !== null && (
                <FormStatus mode="error" title="Не удалось удалить картинку">
                  {deleteError}
                </FormStatus>
              )}
            </Popup>
          )}
        </div>
      )}
    </Subscreen>
  );
}
