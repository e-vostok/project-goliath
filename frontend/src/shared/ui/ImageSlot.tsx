/**
 * ImageSlot — the «Блок картинки» (UI Spec 6, элемент 13, version
 * 0.12.0 unit 6; mockups `docs/06_DESIGN/0.12.0/` boards 13–17): the
 * flag (3:2) or the leader portrait (3:4) shown as the upload button.
 * The loaded picture or the stub IS the button — no labels, icons or
 * overlays anywhere outside registration; the only affordances are the
 * system pointer-hand cursor, the 500 ms «Подсказка» and the 2 px
 * `action` focus ring.
 *
 * `interactive=false` renders a plain picture/stub (other players'
 * pictures never react to the pointer). `interactive=true` renders one
 * real <button> that opens a hidden file input (accept
 * JPEG/PNG/WebP) and reports the picked File through `onPick`. While
 * `busy` the block keeps its size under a dark overlay with the shared
 * spinner and ignores clicks. A picture that fails to load falls back
 * to the stub — no broken-image icon.
 *
 * Only the `registration` size carries the «Загрузить» pill (dark
 * translucent, `action` fill on hover) and the explanatory text block
 * next to the slot — both per boards 13/13б.
 */

import { useRef, useState, type CSSProperties } from 'react';
import { Spinner } from '@vkontakte/vkui';

import type { NationRulesDTO } from '../types';
import { imageUploadMb } from '../../modules/00_core/components/imageErrorTexts';
import { FlagStub } from './FlagStub';
import { PortraitStub } from './PortraitStub';
import { Tooltip } from './Tooltip';
import { FONTS, RADII, SPACING, TEXT_STYLES, tokenVar } from './tokens';

export type ImageSlotKind = 'flag' | 'portrait';
export type ImageSlotSize = 'shtab' | 'registration';

const BOX: Record<
  ImageSlotKind,
  Record<ImageSlotSize, { width: number; height: number; radius: number }>
> = {
  flag: {
    shtab: { width: 96, height: 64, radius: RADII['radius-sm'] },
    registration: { width: 180, height: 120, radius: RADII['radius-md'] },
  },
  portrait: {
    shtab: { width: 72, height: 96, radius: RADII['radius-md'] },
    registration: { width: 120, height: 160, radius: RADII['radius-md'] },
  },
};

const NOUN: Record<ImageSlotKind, string> = {
  flag: 'флаг',
  portrait: 'портрет',
};

/** «JPEG, PNG или WebP» — the file input's accept list. */
const ACCEPT = 'image/jpeg,image/png,image/webp';

/**
 * Open the file chooser for one image — a transient `<input
 * type="file">` clicked synchronously inside the click handler so the
 * browser allows it. The chosen File reaches `onPicked`; cancelling
 * the chooser reports nothing and leaves the open window untouched
 * (0.12.0 unit 7 — «Выбрать другой файл» in the preview window).
 */
export function pickImageFile(onPicked: (file: File) => void): void {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = ACCEPT;
  input.onchange = () => {
    const file = input.files?.[0];
    if (file !== undefined && file !== null) {
      onPicked(file);
    }
  };
  input.click();
}

export interface ImageSlotProps {
  kind: ImageSlotKind;
  size: ImageSlotSize;
  /** Server URL or a local object URL; null renders the stub. */
  src: string | null;
  /** Nation colour `#RRGGBB` filling the flag stub. */
  stubColor?: string;
  alt: string;
  interactive: boolean;
  /** Dark overlay + spinner; clicks are ignored. */
  busy?: boolean;
  /** Tooltip lines (built by the caller); no tip while absent. */
  hintLines?: { first: string; second?: string };
  /** Server rules — the registration side text reads its numbers. */
  rules?: NationRulesDTO | null;
  onPick?: (file: File) => void;
}

export function ImageSlot({
  kind,
  size,
  src,
  stubColor,
  alt,
  interactive,
  busy = false,
  hintLines,
  rules = null,
  onPick,
}: ImageSlotProps) {
  const { width, height, radius } = BOX[kind][size];
  // The failed URL, not a boolean — a new src gets a fresh try.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const showImage = src !== null && src !== failedSrc;
  const noun = NOUN[kind];

  const inner = showImage ? (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      onError={() => setFailedSrc(src)}
      style={{
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        display: 'block',
      }}
    />
  ) : kind === 'flag' ? (
    <FlagStub
      variant={size === 'registration' ? 'registration' : 'card'}
      color={stubColor}
    />
  ) : (
    <PortraitStub variant={size === 'registration' ? 'registration' : 'block'} />
  );

  if (!interactive) {
    return (
      <div
        style={{
          width,
          height,
          borderRadius: radius,
          overflow: 'hidden',
          flexShrink: 0,
        }}
      >
        {inner}
      </div>
    );
  }

  const pick = (files: FileList | null) => {
    const file = files?.[0];
    if (file !== undefined && file !== null) {
      onPick?.(file);
    }
  };

  const button = (
    <button
      type="button"
      aria-label={
        showImage ? `Загрузить другой ${noun}` : `Загрузить ${noun}`
      }
      aria-busy={busy || undefined}
      onClick={() => {
        if (!busy) {
          inputRef.current?.click();
        }
      }}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={(event) => {
        // «Фокус клавиатуры» (UI Spec, элемент 13): the ring is for
        // keyboard focus only — a mouse click must not light it.
        // jsdom may not know the pseudo-class; a throw counts as
        // keyboard focus.
        let keyboard = true;
        try {
          keyboard = event.currentTarget.matches(':focus-visible');
        } catch {
          keyboard = true;
        }
        setFocused(keyboard);
      }}
      onBlur={() => setFocused(false)}
      style={{
        position: 'relative',
        display: 'block',
        flexShrink: 0,
        width,
        height,
        boxSizing: 'border-box',
        overflow: 'hidden',
        padding: 0,
        border: 'none',
        borderRadius: radius,
        background: 'transparent',
        color: '#ffffff',
        boxShadow: `0 0 0 1px ${tokenVar('swatch-edge')}`,
        cursor: 'pointer',
        outline: focused ? `2px solid ${tokenVar('action')}` : 'none',
        outlineOffset: 2,
      }}
    >
      {inner}
      {size === 'registration' && !showImage && (
        <span
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <span
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              height: 30,
              padding: '0 12px',
              borderRadius: RADII['radius-pill'],
              background: hovered
                ? tokenVar('action')
                : 'rgba(0,0,0,0.62)',
              color: hovered ? tokenVar('ground') : '#ffffff',
              fontSize: 12,
              lineHeight: '16px',
              whiteSpace: 'nowrap',
            }}
          >
            <CameraIcon />
            Загрузить
          </span>
        </span>
      )}
      {busy && (
        <span
          style={{
            position: 'absolute',
            inset: 0,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
          }}
        >
          <Spinner size="s" disableAnimation={false} />
          <span style={{ fontSize: 12, lineHeight: '16px' }}>Обработка…</span>
        </span>
      )}
    </button>
  );

  const slot = hintLines ? (
    <Tooltip
      content={
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: SPACING['space-1'],
          }}
        >
          <span>{hintLines.first}</span>
          {hintLines.second !== undefined && (
            <span
              style={{
                fontFamily: FONTS.mono,
                fontSize: 12,
                lineHeight: '16px',
                color: tokenVar('ink-muted'),
              }}
            >
              {hintLines.second}
            </span>
          )}
        </div>
      }
    >
      {button}
    </Tooltip>
  ) : (
    button
  );

  // The sized box keeps the Tooltip's `height: 100%` trigger exactly on
  // the button — in the registration row a taller side note would
  // otherwise stretch it and centre the slot vertically.
  const boxed = (
    <div style={{ width, height, flexShrink: 0 }}>
      {slot}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        tabIndex={-1}
        aria-hidden="true"
        style={{ display: 'none' }}
        onChange={(event) => {
          pick(event.currentTarget.files);
          // Same file must be pickable twice in a row.
          event.currentTarget.value = '';
        }}
      />
    </div>
  );

  if (size !== 'registration') {
    return boxed;
  }
  return (
    <div
      style={{
        display: 'flex',
        gap: SPACING['space-4'],
        alignItems: 'flex-start',
      }}
    >
      {boxed}
      <RegistrationNote kind={kind} rules={rules} />
    </div>
  );
}

/** The camera glyph of the «Загрузить» pill (boards 13/13б). */
function CameraIcon() {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ display: 'block' }}
    >
      <path d="M2 5.2h2.2l1-1.6h5.6l1 1.6H14v7.6H2z" />
      <circle cx={8} cy={8.6} r={2.2} />
    </svg>
  );
}

const noteStyle: CSSProperties = {
  ...TEXT_STYLES['caption'],
  color: tokenVar('ink-muted'),
};

/** The registration side text (boards 13/13б), four fixed lines. */
function RegistrationNote({
  kind,
  rules,
}: {
  kind: ImageSlotKind;
  rules: NationRulesDTO | null;
}) {
  const images = rules?.images;
  const width = kind === 'flag' ? images?.flag_width : images?.portrait_width;
  const height =
    kind === 'flag' ? images?.flag_height : images?.portrait_height;
  const limits =
    images !== undefined && width !== undefined && height !== undefined
      ? `, до ${imageUploadMb(images.max_upload_bytes)} МБ. Размер ${width}×${height} вставится без обрезки.`
      : '.';
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        maxWidth: 460,
        paddingTop: 2,
      }}
    >
      <span style={{ ...TEXT_STYLES['body'], color: tokenVar('ink') }}>
        {kind === 'flag'
          ? 'Нажмите на заглушку, чтобы выбрать картинку флага.'
          : 'Нажмите на заглушку, чтобы выбрать портрет лидера.'}
      </span>
      <div style={noteStyle}>{`JPEG, PNG или WebP${limits}`}</div>
      <div style={noteStyle}>
        {kind === 'flag'
          ? 'Другой размер подгонится по центру. Флаг должен быть горизонтальным: ширина больше высоты.'
          : 'Другой размер подгонится по центру. Портрет должен быть вертикальным: высота больше ширины.'}
      </div>
      <div style={noteStyle}>
        {kind === 'flag'
          ? 'Флаг можно пропустить и загрузить позже в «Штабе»: щелчком по флагу государства. Пока флага нет, показывается цвет государства.'
          : 'Портрет можно пропустить и загрузить позже в «Штабе»: щелчком по портрету лидера. Пока портрета нет, показывается силуэт.'}
      </div>
    </div>
  );
}
