/**
 * NationCell — `nation` column: the shared `NationLabel` (version
 * 0.10.0, unit 6a) — the small flag, or a colour block when the cell
 * has no working `flag_url`, plus the cell's SHORT name; a dash when
 * the cell is null (Spec 5.5 / 1.2).
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
  NationLabel,
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
 * nations table's «name» cell (unit 11): the shared `NationLabel`
 * (`tip` size — small flag or colour block) and the SHORT name in
 * `heading` (unit 6a — the loaded card never substitutes its long
 * `name`), the «Лидер / Провинций / Столица» rows (empty legacy
 * fields show «—»), a separator and the «Нажмите на название…» hint.
 * The cell's name/colour/flag show while the public card loads
 * («Загрузка…»); a failed request shows «Не удалось загрузить» — no
 * error screen, no notice — and is not cached, so the next hover
 * retries.
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
  const shownColor = nation?.color_hex ?? color ?? undefined;
  // Unit 6a: the heading is always the SHORT name — the loaded card
  // only refreshes flag and colour, never replaces it with `name`.
  const shownName = nation?.short_name ?? name;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SPACING['space-2'],
      }}
    >
      <NationLabel
        name={shownName}
        flagUrl={shownFlag}
        color={shownColor}
        size="tip"
      />

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
  const nation = isNationCell(value) ? value : null;

  if (!nation) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  const face = (
    <NationLabel
      name={nation.name}
      flagUrl={nation.flag_url}
      color={nation.color}
      size="cell"
    />
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
