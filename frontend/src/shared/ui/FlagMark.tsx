/**
 * FlagMark — the small flag thumbnail of a table cell or a picture
 * block (0.12.0 unit 9): the nation's uploaded flag at a caller-given
 * box size, `object-fit: cover`. A null or broken `url` (`onError`)
 * falls back to the stub — the nation colour block when `color` is
 * given, `FlagStub` when its variant matches the box, else a plain
 * `surface-inset` block (UI Spec 6, элемент 8: the flag stub IS the
 * nation colour). NationLabel uses the same component for its mark.
 */

import { useState } from 'react';

import { FlagStub } from './FlagStub';
import { tokenVar } from './tokens';

type StubVariant = NonNullable<
  React.ComponentProps<typeof FlagStub>['variant']
>;

/** FlagStub's own box sizes — the variant is used only when it fits. */
const STUB_SIZES: Record<StubVariant, [number, number]> = {
  card: [96, 64],
  registration: [180, 120],
  sub: [48, 32],
  row: [28, 19],
  cell: [22, 14],
};

export function FlagMark({
  url = null,
  color,
  width,
  height,
  radius = 2,
  stubVariant,
}: {
  /** The uploaded flag's URL; null renders the stub. */
  url?: string | null;
  /** Nation `#RRGGBB` — the stub in its colour (beats the grey stub). */
  color?: string;
  width: number;
  height: number;
  radius?: number;
  /** Grey-stub variant — honoured only when its size matches the box. */
  stubVariant?: StubVariant;
}) {
  // The failed URL, not a boolean — a new flag gets a fresh try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);

  if (url !== null && url !== failedUrl) {
    return (
      <img
        src={url}
        alt=""
        width={width}
        height={height}
        onError={() => setFailedUrl(url)}
        style={{
          borderRadius: radius,
          objectFit: 'cover',
          flexShrink: 0,
          display: 'block',
        }}
      />
    );
  }
  if (color !== undefined) {
    return (
      <span
        aria-hidden
        style={{
          width,
          height,
          borderRadius: radius,
          flexShrink: 0,
          display: 'block',
          background: color,
        }}
      />
    );
  }
  if (
    stubVariant !== undefined &&
    STUB_SIZES[stubVariant][0] === width &&
    STUB_SIZES[stubVariant][1] === height
  ) {
    return <FlagStub variant={stubVariant} />;
  }
  return (
    <span
      role="img"
      aria-label="Заглушка флага"
      style={{
        width,
        height,
        borderRadius: radius,
        flexShrink: 0,
        display: 'block',
        background: tokenVar('surface-inset'),
      }}
    />
  );
}
