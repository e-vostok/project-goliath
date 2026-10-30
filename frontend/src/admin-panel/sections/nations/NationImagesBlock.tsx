/**
 * NationImagesBlock — the «Картинки государства» card of the nation
 * edit page (0.12.0 unit 9, mockup screen 18): the flag (240×160) and
 * the leader portrait (120×160) side by side, each with its state —
 * «Загружен <дата>», «Игрок: <name|id>», «<w>×<h> · <N> КБ», the
 * «Показывается в …» line and the red outline «Удалить …» button —
 * or the «Не загружен» stub state with the button disabled. The grey
 * .info note under the columns. The administrator never uploads —
 * «Удалить …» opens the screen-18b confirmation window; a deletion
 * reports onImageDeleted so the parent drops the entry to the stub.
 */

import { useState } from 'react';

import type {
  AdminNationDetailDTO,
  AdminNationImageEntryDTO,
} from '../../../shared/types';
import { FlagMark } from '../../../shared/ui/FlagMark';
import { useNotice } from '../../../shared/ui/Notice';
import { PortraitStub } from '../../../shared/ui/PortraitStub';
import {
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { NationImageDeletePopup } from './NationImageDeletePopup';
import { PanelButton, PanelCard } from './shared';

export type ImageKind = 'flag' | 'portrait';

type ImagesState = AdminNationDetailDTO['images'];

const META: Record<
  ImageKind,
  {
    label: string;
    noun: string;
    box: { width: number; height: number };
    showsLine: string;
    stubLine: string;
    button: string;
  }
> = {
  flag: {
    label: 'Флаг',
    noun: 'флаг',
    box: { width: 240, height: 160 },
    showsLine: 'Показывается в «Штабе», «Реестре» и приказах.',
    stubLine: 'Игрокам показывается цвет государства.',
    button: 'Удалить флаг',
  },
  portrait: {
    label: 'Портрет лидера',
    noun: 'портрет',
    box: { width: 120, height: 160 },
    showsLine: 'Показывается в «Штабе» и на карточке государства.',
    stubLine: 'Игрокам показывается силуэт.',
    button: 'Удалить портрет',
  },
};

const NOTE =
  'Администратор может только удалить картинку: после удаления ' +
  'игроку снова показывается заглушка, и он может загрузить новую. ' +
  'Каждое удаление записывается в журнал.';

/** ISO 8601 UTC → «26.10.2026, 17:05» in the panel's tick timezone. */
const uploadedFmt = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

function uploadedAtText(iso: string): string {
  const moment = new Date(iso);
  return Number.isNaN(moment.getTime()) ? iso : uploadedFmt.format(moment);
}

function kbText(sizeBytes: number): string {
  return `${Math.round(sizeBytes / 1024)} КБ`;
}

/** The portrait's box: the picture or the 120×160 silhouette stub. */
function PortraitBox({ url }: { url: string | null }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const { width, height } = META.portrait.box;
  if (url !== null && url !== failedUrl) {
    return (
      <img
        src={url}
        alt=""
        width={width}
        height={height}
        onError={() => setFailedUrl(url)}
        style={{
          borderRadius: RADII['radius-md'],
          objectFit: 'cover',
          display: 'block',
        }}
      />
    );
  }
  return <PortraitStub variant="registration" />;
}

function ImageColumn({
  kind,
  entry,
  colorHex,
  onDelete,
}: {
  kind: ImageKind;
  entry: AdminNationImageEntryDTO | null;
  colorHex: string;
  onDelete: (kind: ImageKind) => void;
}) {
  const meta = META[kind];
  const caption = {
    ...TEXT_STYLES['caption'],
    color: tokenVar('ink-muted'),
  } as const;
  return (
    <div
      data-testid={`nation-image-${kind}`}
      style={{
        display: 'flex',
        gap: SPACING['space-4'],
        alignItems: 'flex-start',
        minWidth: 0,
      }}
    >
      {kind === 'flag' ? (
        <FlagMark
          url={entry?.url ?? null}
          color={colorHex}
          width={meta.box.width}
          height={meta.box.height}
          radius={8}
        />
      ) : (
        <PortraitBox url={entry?.url ?? null} />
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
          style={{ ...TEXT_STYLES['label'], color: tokenVar('ink-muted') }}
        >
          {meta.label}
        </span>
        {entry === null ? (
          <>
            <span style={TEXT_STYLES['body']}>Не загружен</span>
            <span style={caption}>{meta.stubLine}</span>
          </>
        ) : (
          <>
            <span style={TEXT_STYLES['body']}>
              {`Загружен ${uploadedAtText(entry.uploaded_at)}`}
            </span>
            {entry.uploaded_by !== null && (
              <span style={caption}>
                {entry.uploaded_by.name !== null
                  ? `Игрок: ${entry.uploaded_by.name}`
                  : `Игрок: id ${entry.uploaded_by.vk_user_id}`}
              </span>
            )}
            <span style={caption}>
              {`${entry.width}×${entry.height} · ${kbText(entry.size_bytes)}`}
            </span>
            <span style={caption}>{meta.showsLine}</span>
          </>
        )}
        <div style={{ marginTop: 6 }}>
          <PanelButton
            kind="danger-outline"
            small
            disabled={entry === null}
            testId={`nation-image-delete-${kind}`}
            onClick={() => onDelete(kind)}
          >
            {meta.button}
          </PanelButton>
        </div>
      </div>
    </div>
  );
}

export function NationImagesBlock({
  nationId,
  shortName,
  colorHex,
  images,
  onImagesChanged,
}: {
  nationId: string;
  shortName: string;
  /** The nation's colour fills the flag stub. */
  colorHex: string;
  images: ImagesState;
  /** The parent replaces its images state after a deletion or a save. */
  onImagesChanged: (next: ImagesState) => void;
}) {
  const notify = useNotice();
  const { reportUnauthorized } = useAdminSession();
  const [deleting, setDeleting] = useState<ImageKind | null>(null);

  const dropEntry = (kind: ImageKind) =>
    onImagesChanged({ ...images, [kind]: null });

  const onDeleted = (kind: ImageKind) => {
    setDeleting(null);
    dropEntry(kind);
    notify(
      kind === 'flag'
        ? `Флаг государства «${shortName}» удалён.`
        : `Портрет государства «${shortName}» удалён.`,
    );
  };

  const onGone = () => {
    if (deleting === null) {
      return;
    }
    const kind = deleting;
    setDeleting(null);
    dropEntry(kind);
    notify('Картинки уже нет.');
  };

  return (
    <>
      <PanelCard title="Картинки государства">
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: `${SPACING['space-3']}px ${SPACING['space-4']}px`,
          }}
        >
          <ImageColumn
            kind="flag"
            entry={images.flag}
            colorHex={colorHex}
            onDelete={setDeleting}
          />
          <ImageColumn
            kind="portrait"
            entry={images.portrait}
            colorHex={colorHex}
            onDelete={setDeleting}
          />
        </div>
        <div
          data-testid="nation-images-note"
          style={{
            background: tokenVar('surface-inset'),
            borderRadius: RADII['radius-md'],
            padding: SPACING['space-3'],
            color: tokenVar('ink'),
            ...TEXT_STYLES['body'],
          }}
        >
          {NOTE}
        </div>
      </PanelCard>
      {deleting !== null && images[deleting] !== null && (
        <NationImageDeletePopup
          nationId={nationId}
          kind={deleting}
          entry={images[deleting]!}
          colorHex={colorHex}
          onClose={() => setDeleting(null)}
          onDeleted={() => onDeleted(deleting)}
          onGone={onGone}
          onUnauthorized={reportUnauthorized}
        />
      )}
    </>
  );
}
