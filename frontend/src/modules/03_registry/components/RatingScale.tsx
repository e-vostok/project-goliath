/**
 * RatingScale — the judge-rating bar of the «Реестр» (mockups 26,
 * 26б and 26в, unit 11b): a track with a centre tick at zero, a fill
 * from the centre to the value — `positive` to the right, `danger`
 * to the left, none at zero — and a knob with a 2 px ring in the
 * `surface` colour. The knob never leaves the track: the range maps
 * onto the track minus an inset on each side, exactly like the
 * mockup. A value outside the range is clamped for drawing only —
 * the aria-label still names the real figure («Рейтинг +35 из
 * диапазона −100…+100»).
 *
 * Two sizes: the 72 × 6 px table variant (5 px inset, 10 px knob)
 * and the full-width 8 px tile variant of the «Игрок» screen
 * (7 px inset, 14 px knob).
 */

import { FONTS, TEXT_STYLES, tokenVar } from '../../../shared/ui';
import { REGISTRY_TEXTS } from '../texts';

/** Judge-rating bounds — mirrors the `JUDGE_RATING_MIN`/`MAX`
    constants of `00_core` (Spec D1: model constants, not balance).
    The «Игрок» card carries no scale fields, so the tile draws the
    canonical range. */
export const JUDGE_RATING_MIN = -100;
export const JUDGE_RATING_MAX = 100;

/** The header tip's legend draws this sample fill (mockup 26б). */
const TIP_DEMO_VALUE = 35;

const SIZES = {
  table: {
    height: 6,
    radius: 3,
    inset: 5,
    knob: 10,
    knobTop: -2,
    tickHeight: 12,
    tickTop: -3,
  },
  tile: {
    height: 8,
    radius: 4,
    inset: 7,
    knob: 14,
    knobTop: -3,
    tickHeight: 16,
    tickTop: -4,
  },
} as const;

const fraction = (value: number, min: number, max: number) =>
  max > min ? Math.min(1, Math.max(0, (value - min) / (max - min))) : 0.5;

export function RatingScale({
  value,
  min,
  max,
  size = 'table',
  widthPx,
}: {
  value: number;
  min: number;
  max: number;
  /** `table` — the 6 px cell scale; `tile` — the 8 px card scale. */
  size?: 'table' | 'tile';
  /** Table-size width — 72 px by default, 120 px in the header tip
      legend (mockup 26б). The tile variant is always full width. */
  widthPx?: number;
}) {
  const v = SIZES[size];
  const inner = `(100% - ${2 * v.inset}px)`;
  // Four decimals keep the calc() strings clean (0.675 − 0.5 is
  // 0.17500000000000004 raw — the mockup writes 0.175).
  const round4 = (n: number) => Math.round(n * 10000) / 10000;
  const pos = (frac: number) => `calc(${v.inset}px + ${inner} * ${frac})`;
  const valueFrac = round4(fraction(value, min, max));
  const zeroFrac = round4(fraction(0, min, max));
  const fillFrac = round4(Math.abs(valueFrac - zeroFrac));
  return (
    <span
      role="img"
      aria-label={REGISTRY_TEXTS.ratingAriaLabel(value, min, max)}
      data-testid="rating-scale"
      style={{
        position: 'relative',
        display: 'block',
        flexShrink: 0,
        width: size === 'tile' ? '100%' : (widthPx ?? 72),
        height: v.height,
        borderRadius: v.radius,
        background: tokenVar('surface-inset'),
        boxShadow: `inset 0 0 0 1px ${tokenVar('line')}`,
      }}
    >
      {fillFrac > 0 && (
        <span
          aria-hidden
          data-testid="rating-fill"
          style={{
            position: 'absolute',
            top: 1,
            bottom: 1,
            left: pos(Math.min(zeroFrac, valueFrac)),
            width: `calc(${inner} * ${fillFrac})`,
            background: tokenVar(
              valueFrac > zeroFrac ? 'positive' : 'danger',
            ),
            borderRadius:
              valueFrac > zeroFrac
                ? `0 ${v.radius}px ${v.radius}px 0`
                : `${v.radius}px 0 0 ${v.radius}px`,
          }}
        />
      )}
      <span
        aria-hidden
        data-testid="rating-tick"
        style={{
          position: 'absolute',
          left: pos(zeroFrac),
          top: v.tickTop,
          width: 1,
          height: v.tickHeight,
          background: tokenVar('ink-muted'),
        }}
      />
      <span
        aria-hidden
        data-testid="rating-knob"
        style={{
          position: 'absolute',
          left: pos(valueFrac),
          top: v.knobTop,
          width: v.knob,
          height: v.knob,
          marginLeft: -v.knob / 2,
          borderRadius: '50%',
          background: tokenVar('ink'),
          boxShadow: `0 0 0 2px ${tokenVar('surface')}`,
        }}
      />
    </span>
  );
}

const TIP_CAPTION_STYLE: React.CSSProperties = {
  ...TEXT_STYLES['caption'],
  fontFamily: FONTS.mono,
  color: tokenVar('ink-muted'),
};

/**
 * RatingScaleTip — the «Подсказка» of the «Рейтинг» column header
 * (mockup 26б): the «Судейский рейтинг» title, one sentence with the
 * column's bounds and the legend row «−100 [scale] +100» — the scale
 * draws the legend's sample +35 fill.
 */
export function RatingScaleTip({
  min,
  max,
}: {
  min: number | null;
  max: number | null;
}) {
  const lo = min ?? JUDGE_RATING_MIN;
  const hi = max ?? JUDGE_RATING_MAX;
  return (
    <div>
      <div
        style={{
          fontFamily: FONTS.heading,
          fontWeight: 500,
          fontSize: 14,
          lineHeight: '20px',
        }}
      >
        {REGISTRY_TEXTS.ratingTipTitle}
      </div>
      <div style={{ marginTop: 4 }}>{REGISTRY_TEXTS.ratingTipText(lo, hi)}</div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 8,
        }}
      >
        <span style={TIP_CAPTION_STYLE}>
          {REGISTRY_TEXTS.ratingNumber(lo)}
        </span>
        <RatingScale value={TIP_DEMO_VALUE} min={lo} max={hi} widthPx={120} />
        <span style={TIP_CAPTION_STYLE}>
          {REGISTRY_TEXTS.ratingNumber(hi)}
        </span>
      </div>
    </div>
  );
}
