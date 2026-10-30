/**
 * ImageUploadPreview — the S-size «окно загрузки картинки» (UI Spec 6,
 * элемент 13 and 7 «Ошибка загрузки картинки»; mockups
 * `docs/06_DESIGN/0.12.0/` boards 15, 15б, 16).
 *
 * The picked file is decoded in the browser — `createImageBitmap`
 * (which applies the file's own EXIF rotation), an `<img>` + object
 * URL fallback for engines without it — and the centre-crop result at
 * the TARGET aspect (3:2 flag, 3:4 portrait) is drawn on a canvas.
 * It is only a preview of what the server will do: `onConfirm` always
 * receives the ORIGINAL File.
 *
 * Checks that need no server run first, each replacing the preview
 * with the error block: file above `rules.images.max_upload_bytes` →
 * «Файл больше N МБ…», undecodable → «Это не картинка…», a flag not
 * strictly wider than high / a portrait not strictly higher than wide
 * → the orientation wording — and the primary button becomes «Выбрать
 * другой файл». Server IMAGE_* codes from `onConfirm` land in the same
 * place with the same texts; a network failure shows the shared
 * phrase and «Повторить», which re-runs `onConfirm` (the file stays
 * in the window). While `onConfirm` runs, the buttons are disabled
 * and the window ignores the scrim and Esc (Popup `dirty`).
 */

import { useEffect, useRef, useState } from 'react';
import { Button, Spinner } from '@vkontakte/vkui';

import { ApiError } from '../../../shared/api-client';
import type { NationRulesDTO } from '../../../shared/types';
import { ErrorCodes } from '../../../shared/types';
import {
  FONTS,
  LoadingState,
  Popup,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui';
import { imageErrorText, type NationImageKind } from './imageErrorTexts';

export type ImageUploadMode = 'replace' | 'register';

export interface ImageUploadPreviewProps {
  kind: NationImageKind;
  mode: ImageUploadMode;
  file: File;
  /** Server rules — null skips the size check and the «N МБ» number. */
  rules: NationRulesDTO | null;
  /** Uploads/stores the file; rejects with ApiError or a network error. */
  onConfirm: (file: File) => Promise<void>;
  /** Re-opens the file picker for another file. */
  onPickAnother: () => void;
  onClose: () => void;
}

interface Dims {
  width: number;
  height: number;
}

/** Output sizes when rules have not arrived (config defaults). */
const TARGETS: Record<NationImageKind, { w: number; h: number }> = {
  flag: { w: 600, h: 400 },
  portrait: { w: 600, h: 800 },
};

/** The preview box in the window (boards 15/15б). */
const BOX: Record<NationImageKind, { w: number; h: number }> = {
  flag: { w: 300, h: 200 },
  portrait: { w: 210, h: 280 },
};

const RATIO_TEXT: Record<NationImageKind, string> = {
  flag: '3:2',
  portrait: '3:4',
};

/** Decode via `<img>` + object URL — the engine without createImageBitmap. */
function decodeViaImg(file: File): Promise<{
  img: HTMLImageElement;
  url: string;
  width: number;
  height: number;
}> {
  const url = URL.createObjectURL(file);
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () =>
      resolve({ img, url, width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('decode failed'));
    };
    img.src = url;
  });
}

/**
 * The crop sentence after «Картинка станет X: » — the percent is exact
 * when whole, «около N %» when rounded (board 15 shows both).
 */
function cropSentence(
  kind: NationImageKind,
  dims: Dims,
  targetW: number,
  targetH: number,
): string {
  const instr = kind === 'flag' ? 'флагом' : 'портретом';
  const ratio = RATIO_TEXT[kind];
  const target = targetW / targetH;
  const source = dims.width / dims.height;
  if (Math.abs(source - target) < 0.001) {
    return `Картинка станет ${instr}: пропорция уже ${ratio} — обрезка по центру не нужна.`;
  }
  let where: string;
  let exact: number;
  if (source > target) {
    where = 'с боков срежется';
    exact = ((dims.width - dims.height * target) / dims.width) * 100;
  } else {
    where = 'сверху и снизу срежется';
    exact = ((dims.height - dims.width / target) / dims.height) * 100;
  }
  const rounded = Math.round(exact);
  const pct =
    Math.abs(exact - rounded) < 0.05 ? `${rounded} %` : `около ${rounded} %`;
  return `Картинка станет ${instr}: по центру обрежется до пропорции ${ratio}, ${where} ${pct}.`;
}

export function ImageUploadPreview({
  kind,
  mode,
  file,
  rules,
  onConfirm,
  onPickAnother,
  onClose,
}: ImageUploadPreviewProps) {
  const [dims, setDims] = useState<Dims | null>(null);
  const [decoding, setDecoding] = useState(true);
  /** The original failure object — ApiError or a network error. */
  const [failure, setFailure] = useState<unknown>(null);
  const [uploading, setUploading] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sourceRef = useRef<CanvasImageSource | null>(null);

  const target = {
    flag: {
      w: rules?.images.flag_width ?? TARGETS.flag.w,
      h: rules?.images.flag_height ?? TARGETS.flag.h,
    },
    portrait: {
      w: rules?.images.portrait_width ?? TARGETS.portrait.w,
      h: rules?.images.portrait_height ?? TARGETS.portrait.h,
    },
  }[kind];
  const box = BOX[kind];

  // Local checks then the browser decode — once per picked file.
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    let bitmap: ImageBitmap | null = null;

    setDecoding(true);
    setDims(null);
    setFailure(null);

    if (
      rules !== null &&
      file.size > rules.images.max_upload_bytes
    ) {
      setFailure(
        new ApiError(413, ErrorCodes.IMAGE_TOO_LARGE, 'file above limit'),
      );
      setDecoding(false);
      return undefined;
    }

    const finish = (next: Dims, source: CanvasImageSource) => {
      if (cancelled) {
        return;
      }
      const ok =
        kind === 'flag'
          ? next.width > next.height
          : next.height > next.width;
      if (!ok) {
        setFailure(
          new ApiError(
            422,
            ErrorCodes.IMAGE_ORIENTATION_INVALID,
            'wrong orientation',
          ),
        );
      } else {
        sourceRef.current = source;
        setDims(next);
      }
      setDecoding(false);
    };

    const unsupported = () => {
      if (!cancelled) {
        setFailure(
          new ApiError(415, ErrorCodes.IMAGE_UNSUPPORTED, 'cannot decode'),
        );
        setDecoding(false);
      }
    };

    if (typeof createImageBitmap === 'function') {
      createImageBitmap(file)
        .then((bmp) => {
          bitmap = bmp;
          finish({ width: bmp.width, height: bmp.height }, bmp);
        })
        .catch(unsupported);
    } else {
      decodeViaImg(file)
        .then(({ img, url, width, height }) => {
          objectUrl = url;
          finish({ width, height }, img);
        })
        .catch(unsupported);
    }

    return () => {
      cancelled = true;
      bitmap?.close();
      if (objectUrl !== null) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [file, kind, rules]);

  // Draw the centre-crop preview once the size is known.
  useEffect(() => {
    if (dims === null) {
      return;
    }
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    const source = sourceRef.current;
    if (!canvas || !ctx || !source) {
      return;
    }
    const srcW = dims.width;
    const srcH = dims.height;
    const targetRatio = target.w / target.h;
    const sourceRatio = srcW / srcH;
    let sw = srcW;
    let sh = srcH;
    let sx = 0;
    let sy = 0;
    if (sourceRatio > targetRatio) {
      sw = srcH * targetRatio;
      sx = (srcW - sw) / 2;
    } else {
      sh = srcW / targetRatio;
      sy = (srcH - sh) / 2;
    }
    ctx.drawImage(source, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
  }, [dims, target.w, target.h]);

  const confirm = async () => {
    setUploading(true);
    try {
      await onConfirm(file);
      // The caller owns the window — it closes it on success.
    } catch (error: unknown) {
      setUploading(false);
      setFailure(error ?? new Error('upload failed'));
    }
  };

  const failureCode = failure instanceof ApiError ? failure.code : null;
  const isImageError =
    failureCode === ErrorCodes.IMAGE_TOO_LARGE ||
    failureCode === ErrorCodes.IMAGE_UNSUPPORTED ||
    failureCode === ErrorCodes.IMAGE_ORIENTATION_INVALID;
  const isNetwork = failure !== null && !(failure instanceof ApiError);

  const errorTitle = isNetwork
    ? 'Ошибка сети'
    : failureCode === ErrorCodes.IMAGE_UNSUPPORTED
      ? 'Не удалось взять файл'
      : failureCode === ErrorCodes.IMAGE_TOO_LARGE
        ? 'Файл слишком большой'
        : failureCode === ErrorCodes.IMAGE_ORIENTATION_INVALID
          ? 'Не подходит по форме'
          : 'Ошибка';
  const errorHint =
    failureCode === ErrorCodes.IMAGE_UNSUPPORTED
      ? 'Правило проверяется по содержимому файла, а не по расширению.'
      : failureCode === ErrorCodes.IMAGE_TOO_LARGE
        ? 'Лимит берётся из настроек сервера.'
        : failureCode === ErrorCodes.IMAGE_ORIENTATION_INVALID
          ? kind === 'flag'
            ? 'Квадратная картинка не подходит: у флага ширина должна быть больше высоты.'
            : 'Квадратная картинка не подходит: у портрета высота должна быть больше ширины.'
          : 'Выбранный файл остаётся в окне.';

  const pickAnotherButton = (
    <button
      type="button"
      disabled={uploading}
      onClick={onPickAnother}
      style={{
        marginRight: 'auto',
        padding: 0,
        border: 'none',
        background: 'none',
        color: tokenVar('link'),
        ...TEXT_STYLES['body'],
        cursor: 'pointer',
      }}
    >
      Выбрать другой файл
    </button>
  );

  const footer =
    failure === null ? (
      <>
        {pickAnotherButton}
        <Button
          size="m"
          mode="secondary"
          disabled={uploading}
          onClick={onClose}
        >
          Отмена
        </Button>
        <Button
          size="m"
          mode="primary"
          loading={uploading}
          disabled={decoding || dims === null}
          onClick={() => void confirm()}
        >
          {mode === 'replace'
            ? kind === 'flag'
              ? 'Загрузить флаг'
              : 'Загрузить портрет'
            : kind === 'flag'
              ? 'Использовать флаг'
              : 'Использовать портрет'}
        </Button>
      </>
    ) : (
      <>
        <Button
          size="m"
          mode="secondary"
          disabled={uploading}
          onClick={onClose}
        >
          Закрыть
        </Button>
        {isImageError ? (
          <Button
            size="m"
            mode="primary"
            disabled={uploading}
            onClick={onPickAnother}
          >
            Выбрать другой файл
          </Button>
        ) : (
          <Button
            size="m"
            mode="primary"
            loading={uploading}
            onClick={() => void confirm()}
          >
            Повторить
          </Button>
        )}
      </>
    );

  return (
    <Popup
      size="S"
      icon={kind === 'flag' ? 'flag' : 'person'}
      title={kind === 'flag' ? 'Новый флаг' : 'Портрет лидера'}
      onClose={onClose}
      dirty={uploading}
      testId="popup-image-upload"
      footer={footer}
    >
      {decoding ? (
        <LoadingState height={box.h + 60} />
      ) : failure !== null ? (
        <>
          <div
            role="alert"
            style={{
              display: 'flex',
              gap: 10,
              alignItems: 'flex-start',
              background: tokenVar('surface'),
              border: `1px solid ${tokenVar('danger')}`,
              borderRadius: RADII['radius-md'],
              padding: SPACING['space-3'],
            }}
          >
            <svg
              width={18}
              height={18}
              viewBox="0 0 16 16"
              fill="none"
              stroke={tokenVar('danger')}
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              style={{ flexShrink: 0, marginTop: 1 }}
            >
              <circle cx={8} cy={8} r={6.2} />
              <path d="M8 4.6v4.2M8 11.2h.01" />
            </svg>
            <div>
              <div
                style={{
                  ...TEXT_STYLES['body'],
                  fontWeight: 500,
                  color: tokenVar('danger'),
                }}
              >
                {errorTitle}
              </div>
              <div
                style={{
                  ...TEXT_STYLES['body'],
                  color: tokenVar('ink'),
                  marginTop: 2,
                }}
              >
                {imageErrorText(failure, kind, rules)}
              </div>
            </div>
          </div>
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            {errorHint}
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: SPACING['space-2'],
              position: 'relative',
            }}
          >
            <div
              style={{
                width: box.w,
                height: box.h,
                borderRadius: RADII['radius-md'],
                overflow: 'hidden',
                boxShadow: `0 0 0 1px ${tokenVar('swatch-edge')}`,
                flexShrink: 0,
                position: 'relative',
              }}
            >
              <canvas
                ref={canvasRef}
                width={target.w}
                height={target.h}
                data-testid="image-preview-canvas"
                style={{ display: 'block', width: box.w, height: box.h }}
              />
              {uploading && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'rgba(0,0,0,0.6)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 6,
                    color: '#ffffff',
                  }}
                >
                  <Spinner size="s" disableAnimation={false} />
                  <span style={{ fontSize: 12, lineHeight: '16px' }}>
                    Обработка…
                  </span>
                </div>
              )}
            </div>
            <div
              style={{
                fontFamily: FONTS.mono,
                fontSize: 12,
                lineHeight: '16px',
                color: tokenVar('ink-muted'),
              }}
            >
              {file.name} · {dims?.width}×{dims?.height} → {target.w}×
              {target.h}
            </div>
          </div>
          <div
            style={{
              background: tokenVar('surface'),
              border: `1px solid ${tokenVar('line')}`,
              borderRadius: RADII['radius-md'],
              padding: '10px 12px',
              color: tokenVar('ink'),
            }}
          >
            {dims !== null &&
              cropSentence(kind, dims, target.w, target.h)}
          </div>
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            {mode === 'replace'
              ? kind === 'flag'
                ? 'Прежний флаг заменится новым и будет удалён с сервера.'
                : 'Прежний портрет заменится новым и будет удалён с сервера.'
              : 'Картинка загрузится на сервер, когда вы создадите государство.'}
          </div>
        </>
      )}
    </Popup>
  );
}
