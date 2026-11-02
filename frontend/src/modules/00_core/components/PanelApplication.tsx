/**
 * PanelApplication — the player's own application window («Анкета»,
 * Spec applications §10, mockups 20/20b of version 0.13.0): shown in
 * place of «Штаб» while the application is PENDING. Everything is
 * read-only — a PENDING application cannot be edited, only cancelled.
 *
 * Top: the status plate «На рассмотрении» — «АНКЕТА · ОТПРАВКА №N»,
 * the decision deadline in the tick timezone, the reservation note
 * and the danger-outline «Отменить анкету». Below, the application
 * itself laid out like the nation card: the header (flag, names,
 * motto, colour), «Глава государства» and «Территория» side by side
 * 3 : 2, then «Описание» and «История» as their own blocks.
 *
 * «Отменить анкету» opens the S confirmation of mockup 20b; a
 * confirmed cancel lands back on the registration screen with the
 * «отменена вами» plate (the shell sees the DRAFT and redirects).
 */

import { useState } from 'react';
import { Button, FormStatus, Link } from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import { ErrorCodes } from '../../../shared/types';
import type {
  ApplicationDTO,
  NationPublicDTO,
} from '../../../shared/types';
import {
  BlockTitle,
  FONTS,
  Popup,
  ProvinceChip,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { useSession } from '../hooks/useAuth';
import { CardBlock } from './card/CardBlock';
import { LeaderBlock } from './card/LeaderBlock';
import { NationCardHeader } from './card/NationCardHeader';

/**
 * The deadline rendered like the mockup — «1 ноября, 14:20» in the
 * tick timezone. The configured zone is Europe/Moscow (00_core.yaml
 * `tick_timezone`), the same zone the map's status line hardcodes.
 */
const deadlineDateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric',
  month: 'long',
  timeZone: 'Europe/Moscow',
});
const deadlineTimeFmt = new Intl.DateTimeFormat('ru-RU', {
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Europe/Moscow',
});

/** «1 ноября, 14:20 (МСК)» — the mockup's date, comma, time shape. */
export function formatApplicationDeadline(iso: string): string {
  const date = new Date(iso);
  return `${deadlineDateFmt.format(date)}, ${deadlineTimeFmt.format(date)} (МСК)`;
}

/**
 * The application cast into the public nation view — the card blocks
 * (`NationCardHeader`, `LeaderBlock`) only read the profile fields;
 * the pictures come from `images`, stats and ids mean nothing here.
 */
export function applicationAsNation(
  application: ApplicationDTO,
): NationPublicDTO {
  return {
    id: '',
    created_at: '',
    name: application.name,
    short_name: application.short_name,
    color_hex: application.color_hex,
    motto: application.motto,
    description: application.description,
    flag_url: application.images.flag?.url ?? null,
    flag_thumb_url: application.images.flag?.thumb_url ?? null,
    province_ids: application.provinces.map((province) => province.id),
    capital_province_id: application.capital_province_id,
    capital_name: application.capital_name,
    leader_name: application.leader_name,
    leader_title: application.leader_title,
    leader_bio: application.leader_bio,
    portrait_url: application.images.portrait?.url ?? null,
    portrait_thumb_url: application.images.portrait?.thumb_url ?? null,
    history_url: application.history_url,
    level: 0,
    judge_rating: 0,
  };
}

/** The clock glyph of the status plate — 22 px, stroke, signal-ink. */
function ClockMark() {
  return (
    <svg
      width={22}
      height={22}
      viewBox="0 0 16 16"
      fill="none"
      stroke={tokenVar('signal-ink')}
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <circle cx="8" cy="8" r="5.6" />
      <path d="M8 4.8V8l2.2 1.4" />
    </svg>
  );
}

function StatusPlate({
  application,
  onCancel,
}: {
  application: ApplicationDTO;
  onCancel: () => void;
}) {
  return (
    <section
      data-testid="application-status"
      style={{
        background: tokenVar('surface'),
        borderRadius: RADII['radius-lg'],
        borderLeft: `4px solid ${tokenVar('signal')}`,
        padding: SPACING['space-4'],
        display: 'flex',
        alignItems: 'center',
        gap: SPACING['space-4'],
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 44,
          height: 44,
          flexShrink: 0,
          borderRadius: RADII['radius-md'],
          background: tokenVar('surface-inset'),
        }}
      >
        <ClockMark />
      </span>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>
        <div
          style={{
            ...TEXT_STYLES['label'],
            color: tokenVar('ink-muted'),
          }}
        >
          {`Анкета · отправка №${application.submissions}`}
        </div>
        <div
          style={{
            ...TEXT_STYLES['heading'],
            fontSize: 18,
            lineHeight: '22px',
            color: tokenVar('ink'),
            marginTop: 2,
          }}
        >
          На рассмотрении
        </div>
        <div
          style={{
            ...TEXT_STYLES['body'],
            color: tokenVar('ink'),
            marginTop: 4,
          }}
        >
          {application.review_deadline_at !== null
            ? `Решение будет принято не позже ${formatApplicationDeadline(
                application.review_deadline_at,
              )}. О результате напишет сообщество ВКонтакте.`
            : 'О результате напишет сообщество ВКонтакте.'}
        </div>
        <div
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
            marginTop: 4,
          }}
        >
          Провинции, цвет и оба названия закреплены за вами до решения.
          Править анкету нельзя — только отменить.
        </div>
      </div>
      <div style={{ flexShrink: 0 }}>
        {/* Amber outline per mockup 20 — VKUI's danger/negative reads
            red; the plate button is signal-amber, the red only lands
            on the confirm inside the popup (mockup 20b). */}
        <button
          type="button"
          data-testid="open-cancel-application"
          onClick={onCancel}
          style={{
            height: 36,
            padding: '0 16px',
            borderRadius: RADII['radius-md'],
            border: `1px solid ${tokenVar('signal')}`,
            background: 'transparent',
            color: tokenVar('signal-ink'),
            ...TEXT_STYLES['body'],
            fontWeight: 600,
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          Отменить анкету
        </button>
      </div>
    </section>
  );
}

/** «Территория» of the application — names arrive inside the DTO. */
export function ApplicationTerritory({
  application,
}: {
  application: ApplicationDTO;
}) {
  const provinces = application.provinces;
  return (
    <CardBlock testId="application-territory-block">
      <BlockTitle
        icon="map"
        title="Территория"
        trailing={
          provinces.length > 0 ? (
            <span
              style={{
                fontFamily: FONTS.mono,
                fontSize: 13,
                color: tokenVar('ink-muted'),
              }}
            >
              {provinces.length}
            </span>
          ) : undefined
        }
      />
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '6px 6px',
          alignItems: 'center',
        }}
      >
        {provinces.map((province) => (
          <ProvinceChip
            key={province.id}
            name={province.name}
            capital={province.is_capital}
            capitalName={application.capital_name ?? undefined}
          />
        ))}
      </div>
    </CardBlock>
  );
}

export function PanelApplication({
  application,
  onChanged,
}: {
  application: ApplicationDTO;
  /** Called after a settled cancel — the shell refetches and reroutes. */
  onChanged: () => void;
}) {
  const { token } = useSession();
  const nation = applicationAsNation(application);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  const handleCancel = async () => {
    if (cancelling) {
      return;
    }
    setCancelling(true);
    setCancelError(null);
    try {
      await api.cancelApplication(token);
      setConfirmOpen(false);
      onChanged();
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.code === ErrorCodes.APPLICATION_NOT_PENDING
      ) {
        // Already decided or cancelled elsewhere — close and refresh
        // so the shell reroutes (audit of PR 267).
        setConfirmOpen(false);
        onChanged();
        return;
      }
      setCancelError(errorText(error));
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div
      data-testid="panel-application"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-3'],
        padding: SPACING['space-4'],
        boxSizing: 'border-box',
        maxWidth: SIZES['win-screen'],
      }}
    >
      <StatusPlate
        application={application}
        onCancel={() => {
          setCancelError(null);
          setConfirmOpen(true);
        }}
      />

      <NationCardHeader nation={nation} />

      <div
        data-testid="application-card-row"
        style={{
          display: 'grid',
          gridTemplateColumns: '3fr 2fr',
          gap: SPACING['space-3'],
          alignItems: 'start',
        }}
      >
        <LeaderBlock nation={nation} />
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
                  style={{ color: tokenVar('link'), overflowWrap: 'anywhere' }}
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

      {confirmOpen && (
        <Popup
          size="S"
          title="⚠&#xFE0E; Отменить анкету?"
          onClose={() => setConfirmOpen(false)}
          testId="popup-cancel-application"
          footer={
            <>
              <Button
                size="m"
                mode="secondary"
                disabled={cancelling}
                onClick={() => setConfirmOpen(false)}
              >
                Не отменять
              </Button>
              <Button
                size="m"
                appearance="negative"
                loading={cancelling}
                data-testid="confirm-cancel-application"
                onClick={() => void handleCancel()}
              >
                Отменить анкету
              </Button>
            </>
          }
        >
          <div
            style={{ ...TEXT_STYLES['body'], color: tokenVar('ink') }}
          >
            Закрепление провинций, цвета и названий будет снято. Анкета
            сохранится как черновик: вы сможете исправить её и отправить
            снова.
          </div>
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            Администратор увидит, что анкета отозвана, и уберёт её из
            очереди.
          </div>
          {cancelError !== null && (
            <FormStatus mode="error" title="Не удалось отменить анкету">
              {cancelError}
            </FormStatus>
          )}
        </Popup>
      )}
    </div>
  );
}
