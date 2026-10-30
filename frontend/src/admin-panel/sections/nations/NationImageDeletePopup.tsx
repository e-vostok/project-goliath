/**
 * NationImageDeletePopup — the «Удаление флага» / «Удаление портрета»
 * S-size confirmation window (0.12.0 unit 9, mockup screen 18b) over
 * the nation edit page.
 *
 * On open it loads GET /admin/nations/{id}/images/{kind}/delete-preview
 * — the confirm button stays disabled until the preview is there; the
 * shared loading and failure states apply («Повторить» on a failure).
 * The body shows the picture thumbnail, «Удалить <вид> государства
 * «<краткое>»?», the kind sentence and the grey «Что будет:» box built
 * from the server's consequences[].text verbatim. NO retyped
 * confirmation. Confirm POSTs the delete: a success closes the window
 * and reports onDeleted (the block drops to the stub + Notice);
 * a 404 IMAGE_NOT_FOUND reports onGone (the picture left a moment
 * ago); other refusals land inside the open popup; a 401 ends the
 * session through onUnauthorized.
 */

import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import { errorText } from '../../../shared/errorTexts';
import type {
  AdminNationImageDeletePreviewDTO,
  AdminNationImageEntryDTO,
} from '../../../shared/types';
import { FlagMark } from '../../../shared/ui/FlagMark';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { Popup } from '../../../shared/ui/Popup';
import { PortraitStub } from '../../../shared/ui/PortraitStub';
import {
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelButton } from './shared';
import type { ImageKind } from './NationImagesBlock';

const META: Record<
  ImageKind,
  {
    title: string;
    button: string;
    /** The sentence under the «Удалить … ?» heading (mockup 18b). */
    sentence: string;
    thumb: { width: number; height: number };
  }
> = {
  flag: {
    title: 'Удаление флага',
    button: 'Удалить флаг',
    sentence:
      'Игроки увидят вместо флага заглушку — цвет государства. ' +
      'Владелец сможет загрузить новый флаг.',
    thumb: { width: 150, height: 100 },
  },
  portrait: {
    title: 'Удаление портрета',
    button: 'Удалить портрет',
    sentence:
      'Игроки увидят вместо портрета заглушку — силуэт. ' +
      'Владелец сможет загрузить новый портрет.',
    thumb: { width: 72, height: 96 },
  },
};

/** The mockup's «Что будет:» line — server texts verbatim, sentences. */
function consequencesText(preview: AdminNationImageDeletePreviewDTO): string {
  const texts = preview.consequences.map((c) => c.text);
  if (texts.length === 0) {
    return '';
  }
  const head = texts[0];
  const tail = texts
    .slice(1)
    .map((text) => text.charAt(0).toUpperCase() + text.slice(1))
    .join('. ');
  return tail === '' ? `${head}.` : `${head}. ${tail}.`;
}

export function NationImageDeletePopup({
  nationId,
  kind,
  entry,
  colorHex,
  onClose,
  onDeleted,
  onGone,
  onUnauthorized,
}: {
  nationId: string;
  kind: ImageKind;
  /** The block's current entry — supplies the thumbnail. */
  entry: AdminNationImageEntryDTO;
  /** The nation colour fills the flag stub fallback. */
  colorHex: string;
  onClose: () => void;
  /** Deletion succeeded. */
  onDeleted: () => void;
  /** 404 IMAGE_NOT_FOUND — someone deleted it a moment ago. */
  onGone: () => void;
  onUnauthorized: () => void;
}) {
  const { token } = useAdminSession();
  const meta = META[kind];

  const [preview, setPreview] =
    useState<AdminNationImageDeletePreviewDTO | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadPreview = useCallback(() => {
    setPreview(null);
    setPreviewFailed(false);
    api
      .adminNationImageDeletePreview(token, nationId, kind)
      .then(setPreview)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          onUnauthorized();
          return;
        }
        setPreviewFailed(true);
      });
  }, [token, nationId, kind, onUnauthorized]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  const runDelete = async () => {
    setBusy(true);
    setDeleteError(null);
    try {
      await api.adminNationImageDelete(token, nationId, kind);
      onDeleted();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onUnauthorized();
        return;
      }
      if (error instanceof ApiError && error.code === 'IMAGE_NOT_FOUND') {
        onGone();
        return;
      }
      // The popup stays open — the administrator reads the reason.
      setDeleteError(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const thumbUrl = entry.thumb_url;
  const thumb = META[kind].thumb;

  return (
    <Popup
      size="S"
      title={meta.title}
      testId="nation-image-delete-popup"
      onClose={onClose}
      footer={
        <>
          <PanelButton disabled={busy} onClick={onClose}>
            Отмена
          </PanelButton>
          <PanelButton
            kind="danger"
            disabled={busy || preview === null}
            testId="confirm-image-delete"
            onClick={() => void runDelete()}
          >
            {meta.button}
          </PanelButton>
        </>
      }
    >
      <div
        style={{
          display: 'flex',
          gap: SPACING['space-4'],
          alignItems: 'flex-start',
        }}
      >
        {kind === 'flag' ? (
          <FlagMark
            url={thumbUrl}
            color={colorHex}
            width={thumb.width}
            height={thumb.height}
            radius={8}
          />
        ) : thumbUrl !== null ? (
          <img
            src={thumbUrl}
            alt=""
            width={thumb.width}
            height={thumb.height}
            style={{
              borderRadius: RADII['radius-md'],
              objectFit: 'cover',
              display: 'block',
            }}
          />
        ) : (
          <PortraitStub variant="block" />
        )}
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            minWidth: 0,
          }}
        >
          <span
            style={{
              ...TEXT_STYLES['heading'],
              color: tokenVar('ink'),
            }}
          >
            {`Удалить ${
              kind === 'flag' ? 'флаг' : 'портрет'
            } государства «${preview?.short_name ?? '…'}»?`}
          </span>
          <span style={TEXT_STYLES['body']}>{meta.sentence}</span>
        </div>
      </div>

      {preview === null && !previewFailed && <LoadingState height={60} />}
      {previewFailed && (
        <span
          data-testid="image-delete-preview-error"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            ...TEXT_STYLES['caption'],
            color: tokenVar('danger'),
          }}
        >
          Не удалось загрузить сведения о картинке.
          <PanelButton
            testId="image-delete-preview-retry"
            onClick={loadPreview}
          >
            Повторить
          </PanelButton>
        </span>
      )}
      {preview !== null && (
        <div
          data-testid="image-delete-consequences"
          style={{
            background: tokenVar('surface-inset'),
            borderRadius: RADII['radius-md'],
            padding: SPACING['space-3'],
            color: tokenVar('ink'),
            ...TEXT_STYLES['body'],
          }}
        >
          <b style={{ fontWeight: 500 }}>Что будет:</b>{' '}
          {consequencesText(preview)}
        </div>
      )}

      {deleteError !== null && (
        <span
          data-testid="image-delete-error"
          style={{ ...TEXT_STYLES['caption'], color: tokenVar('danger') }}
        >
          {deleteError}
        </span>
      )}
    </Popup>
  );
}
