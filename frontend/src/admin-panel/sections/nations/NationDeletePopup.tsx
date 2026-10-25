/**
 * NationDeletePopup — the «Удалить государство» S-size popup
 * (0.11.0 unit 8c, mockup screen 03d) over the nations list.
 *
 * On open it loads GET /admin/nations/{id}/delete-preview — the
 * provinces the nation frees plus every module's consequence lines —
 * and shows them as the «Исчезнет:» bullets: the nation with its full
 * name, «N провинций станут свободными: <names>» (up to 8 names, then
 * «и ещё K»), then one bullet per consequence text. «Удалить
 * государство» stays disabled until the administrator retypes the
 * short name exactly; preview loading and failure use the shared
 * states (a failed preview keeps the button disabled and offers
 * «Повторить»). Server refusals land inside the popup — it stays
 * open. A 401 ends the session through the frame's
 * reportUnauthorized; a success reports onDeleted so the section can
 * notice and reload.
 */

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminNationDeletePreviewDTO,
  AdminNationDTO,
} from '../../../shared/types';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { Popup } from '../../../shared/ui/Popup';
import {
  RADII,
  SIZES,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelButton } from './shared';

/** Province names past this count collapse into «и ещё K». */
const PROVINCE_NAMES_SHOWN = 8;

/** «провинция / провинции / провинций» for the freed-provinces bullet. */
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
 * «N провинций станут свободными: Рига, Юрмала…» — names up to
 * PROVINCE_NAMES_SHOWN, the rest as «и ещё K». A province without a
 * display name falls back to «#id».
 */
function provincesLine(preview: AdminNationDeletePreviewDTO): string {
  const total = preview.provinces.length;
  const names = preview.provinces
    .slice(0, PROVINCE_NAMES_SHOWN)
    .map((province) => province.name ?? `#${province.id}`)
    .join(', ');
  const tail = total > PROVINCE_NAMES_SHOWN ? ` и ещё ${total - PROVINCE_NAMES_SHOWN}` : '';
  const subject =
    total === 1
      ? '1 провинция станет свободной'
      : `${total} ${provincesWord(total)} станут свободными`;
  return `${subject}: ${names}${tail}`;
}

/** The «Исчезнет:» bullets — the nation, the provinces, the hooks' lines. */
function consequenceLines(preview: AdminNationDeletePreviewDTO): string[] {
  const lines = [
    `государство «${preview.short_name}» (${preview.name})`,
  ];
  if (preview.provinces.length > 0) {
    lines.push(provincesLine(preview));
  }
  for (const consequence of preview.consequences) {
    lines.push(consequence.text);
  }
  return lines;
}

export function NationDeletePopup({
  target,
  onClose,
  onDeleted,
}: {
  /** The list row the «Удалить…» was clicked on. */
  target: AdminNationDTO;
  onClose: () => void;
  /** Deletion succeeded — the section notices and reloads the list. */
  onDeleted: (shortName: string) => void;
}) {
  const { token, reportUnauthorized } = useAdminSession();

  const [preview, setPreview] = useState<AdminNationDeletePreviewDTO | null>(
    null,
  );
  const [previewFailed, setPreviewFailed] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadPreview = useCallback(() => {
    setPreview(null);
    setPreviewFailed(false);
    api
      .adminNationDeletePreview(token, target.id)
      .then(setPreview)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        setPreviewFailed(true);
      });
  }, [token, target.id, reportUnauthorized]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  const runDelete = async () => {
    setBusy(true);
    setDeleteError(null);
    try {
      await api.adminNationDelete(token, target.id, typed.trim());
      onDeleted(target.short_name);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        reportUnauthorized();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setDeleteError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const expected = target.short_name;
  const ownerName = target.owner_name ?? `VK ${target.owner_vk_user_id}`;
  const ready = preview !== null && typed.trim() === expected;

  return (
    <Popup
      size="S"
      title={`Удалить государство «${target.short_name}»?`}
      testId="nation-delete-popup"
      dirty={typed !== ''}
      onClose={onClose}
      footer={
        <>
          <PanelButton disabled={busy} onClick={onClose}>
            Отмена
          </PanelButton>
          <PanelButton
            kind="danger"
            disabled={busy || !ready}
            testId="confirm-nation-delete"
            onClick={() => void runDelete()}
          >
            Удалить государство
          </PanelButton>
        </>
      }
    >
      <span style={TEXT_STYLES['body']}>
        {`Это нельзя отменить. Игрок ${ownerName} останется в игре без ` +
          'государства и сможет создать новое. Исчезнет:'}
      </span>
      {preview === null && !previewFailed && <LoadingState height={60} />}
      {previewFailed && (
        <span
          data-testid="nation-delete-preview-error"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            ...TEXT_STYLES['caption'],
            color: tokenVar('danger'),
          }}
        >
          Не удалось загрузить список последствий.
          <PanelButton testId="nation-delete-preview-retry" onClick={loadPreview}>
            Повторить
          </PanelButton>
        </span>
      )}
      {preview !== null && (
        <ul
          data-testid="nation-delete-consequences"
          style={{
            margin: 0,
            paddingLeft: 20,
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
          }}
        >
          {consequenceLines(preview).map((line, index, lines) => (
            <li key={line} style={TEXT_STYLES['body']}>
              {line}
              {index === lines.length - 1 ? '.' : ';'}
            </li>
          ))}
        </ul>
      )}
      {/* The mockup's .fld: a normal-case caption label above the field. */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          minWidth: 0,
        }}
      >
        <label
          htmlFor="nation-delete-confirm"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          Для подтверждения введите краткое название: {expected}
        </label>
        <input
          id="nation-delete-confirm"
          value={typed}
          onChange={(event) => setTyped(event.currentTarget.value)}
          onKeyDown={(event) => {
            // Enter never submits anything anywhere in the app.
            if (event.key === 'Enter') {
              event.preventDefault();
            }
          }}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            height: SIZES['button-h'],
            padding: '0 12px',
            borderRadius: RADII['radius-md'],
            background: tokenVar('surface-inset'),
            border: `1px solid ${tokenVar('ink-faint')}`,
            color: tokenVar('ink'),
            ...TEXT_STYLES['body'],
          }}
        />
      </div>
      {deleteError !== null && (
        <span
          data-testid="nation-delete-error"
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('danger'),
          }}
        >
          {deleteError}
        </span>
      )}
    </Popup>
  );
}
