/**
 * NationLabel — the shared nation signature (version 0.10.0, unit 6a):
 * the small flag and the nation name on one line, gap 8. The flag is
 * 24×16 (`cell` — registry rows and marks) or 32×22 (`tip` — tooltip
 * headings), 2 px rounding, `object-fit: cover`. A missing or broken
 * `flagUrl` (`onError`) falls back to a same-size block filled with the
 * nation colour — a block, never the old colour dot — and with no
 * colour either, to `FlagStub`. The name ellipsizes and is never
 * empty. `size="tip"` additionally sets the `heading` text style.
 */

import { useState } from 'react';

import { FlagStub } from './FlagStub';
import { TEXT_STYLES, tokenVar } from './tokens';

const SIZES = {
  cell: { width: 22, height: 14, stub: 'cell' },
  tip: { width: 28, height: 19, stub: 'row' },
  sub: { width: 48, height: 32, stub: 'sub' },
} as const;

export function NationLabel({
  name,
  flagUrl = null,
  color,
  size,
}: {
  name: string;
  flagUrl?: string | null;
  color?: string;
  size: keyof typeof SIZES;
}) {
  // The failed URL, not a boolean — a new flag gets a fresh try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const { width, height, stub } = SIZES[size];
  const markRadius = size === 'sub' ? 4 : 2;

  const mark =
    flagUrl && failedUrl !== flagUrl ? (
      <img
        src={flagUrl}
        alt=""
        width={width}
        height={height}
        style={{
          borderRadius: markRadius,
          objectFit: 'cover',
          flexShrink: 0,
          display: 'block',
        }}
        onError={() => setFailedUrl(flagUrl)}
      />
    ) : color ? (
      <span
        aria-hidden
        style={{
          width,
          height,
          borderRadius: markRadius,
          flexShrink: 0,
          display: 'block',
          background: color,
        }}
      />
    ) : (
      <FlagStub variant={stub} />
    );

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0,
        maxWidth: '100%',
      }}
    >
      {mark}
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          ...(size === 'tip'
            ? { ...TEXT_STYLES['heading'], color: tokenVar('ink') }
            : {}),
          ...(size === 'sub'
            ? {
                ...TEXT_STYLES['heading'],
                fontSize: 20,
                lineHeight: '24px',
              }
            : {}),
        }}
      >
        {name}
      </span>
    </span>
  );
}
