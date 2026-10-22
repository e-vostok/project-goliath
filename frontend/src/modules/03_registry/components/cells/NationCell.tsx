/**
 * NationCell — `nation` column: the nation's flag image when the cell
 * carries `flag_url`, otherwise the colour dot as before; plus the
 * name, or a dash when the cell is null (Spec 5.5 / 1.2).
 *
 * Since unit 14c a cell with a non-null `id` is a button — same look
 * as the plain cell, `action` text colour, underline on hover/focus —
 * that opens the nation subscreen. A null `id` (the orders table's
 * snapshot, a nation-less player) stays plain text and gets NO
 * tooltip.
 *
 * Since unit 11 a cell with a non-null `id` also carries the
 * «Подсказка» (UI Spec 3.4): `NationTip` fetches the public card via
 * `fetchNationTip` (60 s cache) and shows leader, province count and
 * capital — a shortened card, never the only place of the data.
 */

import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import {
  RADII,
  SPACING,
  TEXT_STYLES,
  Tooltip,
  TooltipRow,
  tokenVar,
} from '../../../../shared/ui';
import type { NationPublicDTO } from '../../../../shared/types';
import { useSession } from '../../../00_core/hooks/useAuth';
import { fetchNationTip } from '../../lib/nationTipCache';
import { isNationCell, type RegistryCell } from '../../types';
import { REGISTRY_TEXTS } from '../../texts';

const NATION_TIP_TEXTS = {
  loading: 'Загрузка…',
  loadFailed: 'Не удалось загрузить',
  leader: 'Лидер',
  provinces: 'Провинций',
  capital: 'Столица',
  openHint: 'Нажмите на название, чтобы открыть государство',
};

/**
 * NationTip — the «Подсказка» content of a nation cell and of the
 * nations table's «name» cell (unit 11): the small flag (or colour
 * dot) and the FULL name in `heading`, the «Лидер / Провинций /
 * Столица» rows (empty legacy fields show «—»), a separator and the
 * «Нажмите на название…» hint. The cell's name/colour/flag show while
 * the public card loads («Загрузка…»); a failed request shows
 * «Не удалось загрузить» — no error screen, no notice — and is not
 * cached, so the next hover retries.
 */
export function NationTip({
  nationId,
  name,
  color,
  flagUrl,
}: {
  nationId: string;
  /** The cell's display name — shown until the card arrives. */
  name: string;
  /** The cell's colour and flag — fallbacks while the card loads. */
  color?: string;
  flagUrl?: string | null;
}) {
  const { token } = useSession();
  const [nation, setNation] = useState<NationPublicDTO | null>(null);
  const [failed, setFailed] = useState(false);
  const [flagBroken, setFlagBroken] = useState(false);

  useEffect(() => {
    let alive = true;
    fetchNationTip(token, nationId).then(
      (data) => {
        if (alive) {
          setNation(data);
        }
      },
      () => {
        if (alive) {
          setFailed(true);
        }
      },
    );
    return () => {
      alive = false;
    };
  }, [token, nationId]);

  const shownFlag = nation?.flag_url ?? flagUrl ?? null;
  const shownColor = nation?.color_hex ?? color ?? null;
  const shownName = nation?.name ?? name;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-2'],
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-2'],
        }}
      >
        {shownFlag !== null && !flagBroken ? (
          <img
            src={shownFlag}
            alt=""
            width={18}
            height={12}
            style={{
              borderRadius: RADII['radius-sm'],
              flexShrink: 0,
              display: 'block',
            }}
            onError={() => setFlagBroken(true)}
          />
        ) : shownColor !== null ? (
          <span
            aria-hidden
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              flexShrink: 0,
              background: shownColor,
            }}
          />
        ) : null}
        <span style={{ ...TEXT_STYLES['heading'], color: tokenVar('ink') }}>
          {shownName}
        </span>
      </div>

      {nation === null && !failed && (
        <div style={{ color: tokenVar('ink-muted') }}>
          {NATION_TIP_TEXTS.loading}
        </div>
      )}
      {failed && (
        <div style={{ color: tokenVar('ink-muted') }}>
          {NATION_TIP_TEXTS.loadFailed}
        </div>
      )}
      {nation !== null && (
        <>
          <TooltipRow
            label={NATION_TIP_TEXTS.leader}
            value={nation.leader_name ?? REGISTRY_TEXTS.emptyValue}
          />
          <TooltipRow
            label={NATION_TIP_TEXTS.provinces}
            value={nation.province_ids.length}
          />
          <TooltipRow
            label={NATION_TIP_TEXTS.capital}
            value={nation.capital_name ?? REGISTRY_TEXTS.emptyValue}
          />
          <div
            aria-hidden
            style={{ height: 1, background: tokenVar('line') }}
          />
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            {NATION_TIP_TEXTS.openHint}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The link look every nation-opening cell shares (unit 14c): plain
 * cell content on a transparent `action`-coloured button that
 * underlines on hover/focus and ellipsizes like a text cell. No
 * `title` — the «Подсказка» (unit 11) already names the nation.
 */
export function NationOpenLink({
  onOpen,
  children,
}: {
  onOpen?: () => void;
  children: ReactNode;
}) {
  const [hot, setHot] = useState(false);
  return (
    <button
      type="button"
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
  // An `id: null` snapshot (the orders table) — plain text, no tip.
  if (nationId === null) {
    return <span title={nation.name}>{face}</span>;
  }

  const body =
    onOpen === undefined ? (
      <span>{face}</span>
    ) : (
      <NationOpenLink onOpen={() => onOpen(nationId)}>{face}</NationOpenLink>
    );

  return (
    <Tooltip
      content={() => (
        <NationTip
          nationId={nationId}
          name={nation.name}
          color={nation.color}
          flagUrl={nation.flag_url}
        />
      )}
    >
      {body}
    </Tooltip>
  );
}
