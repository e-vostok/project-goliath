/**
 * NationCell — `nation` column: the nation's flag image when the cell
 * carries `flag_url`, otherwise the colour dot as before; plus the
 * name, or a dash when the cell is null (Spec 5.5 / 1.2).
 *
 * Since unit 14c a cell with a non-null `id` is a button — same look
 * as the plain cell, `action` text colour, underline on hover/focus —
 * that opens the nation subscreen. A null `id` (the orders table's
 * snapshot, a nation-less player) stays plain text.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';

import { tokenVar } from '../../../../shared/ui';
import { isNationCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

/**
 * The link look every nation-opening cell shares (unit 14c): plain
 * cell content on a transparent `action`-coloured button that
 * underlines on hover/focus and ellipsizes like a text cell.
 */
export function NationOpenLink({
  title,
  onOpen,
  children,
}: {
  /** The full nation name — shown by the browser on a long cell. */
  title: string;
  onOpen?: () => void;
  children: ReactNode;
}) {
  const [hot, setHot] = useState(false);
  return (
    <button
      type="button"
      title={title}
      onClick={onOpen}
      onMouseEnter={() => setHot(true)}
      onMouseLeave={() => setHot(false)}
      onFocus={() => setHot(true)}
      onBlur={() => setHot(false)}
      style={{
        display: 'block',
        width: '100%',
        minWidth: 0,
        border: 0,
        padding: 0,
        background: 'transparent',
        font: 'inherit',
        textAlign: 'left',
        cursor: 'pointer',
        color: tokenVar('action'),
        textDecoration: hot ? 'underline' : 'none',
        overflow: 'hidden',
        whiteSpace: 'nowrap',
        textOverflow: 'ellipsis',
      }}
    >
      {children}
    </button>
  );
}

export function NationCell({
  value,
  onOpen,
}: {
  value: RegistryCell;
  /** Opens the nation subscreen (unit 14c); called with the cell id. */
  onOpen?: (nationId: string) => void;
}) {
  // The failed URL, not a flag — a different row landing here after a
  // re-sort must get a fresh try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const nation = isNationCell(value) ? value : null;

  if (!nation) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  const face = (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        minWidth: 0,
        maxWidth: '100%',
      }}
    >
      {nation.flag_url && failedUrl !== nation.flag_url ? (
        <img
          src={nation.flag_url}
          alt=""
          width={18}
          height={12}
          style={{ borderRadius: 2, flexShrink: 0, display: 'block' }}
          onError={() => setFailedUrl(nation.flag_url)}
        />
      ) : (
        <span
          aria-hidden
          style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            flexShrink: 0,
            background: nation.color,
          }}
        />
      )}
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {nation.name}
      </span>
    </span>
  );

  const nationId = nation.id;
  if (nationId === null || onOpen === undefined) {
    return <span title={nation.name}>{face}</span>;
  }

  return (
    <NationOpenLink title={nation.name} onOpen={() => onOpen(nationId)}>
      {face}
    </NationOpenLink>
  );
}
