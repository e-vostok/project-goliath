/**
 * useOwnStats — the player's «Уровень» and «Судейский рейтинг» tiles
 * of the nation card.
 *
 * There is no per-player stats endpoint: the Registry already serves
 * both numbers in its `players` table (columns `level`,
 * `judge_rating`; backend `_03_registry/sources.py`). The cheapest
 * existing client route is one `GET /registry/tables/players` and a
 * match on the row's `nation` cell — the Registry reveals no player
 * identity (INV-R2), but a nation's display name (short_name or name)
 * and colour are both unique server-side, so the cell pinpoints the
 * owner's row exactly.
 *
 * A failed request, a truncated table without the owner's row or a
 * cell that is not a plain number all resolve to `stats: null` — the
 * tiles show «—» and the card stays usable.
 */

import { useEffect, useState } from 'react';

import { registryApi } from '../../../03_registry/api';
import { isNationCell, type RegistryRowDTO } from '../../../03_registry/types';
import type { NationDTO } from '../../../../shared/types';
import { useSession } from '../../hooks/useAuth';

export interface OwnStats {
  level: number | null;
  judgeRating: number | null;
}

export type OwnStatsState =
  | { status: 'loading'; stats: null }
  | { status: 'error'; stats: null; error: Error }
  | { status: 'ready'; stats: OwnStats | null };

const PLAYERS_TABLE_ID = 'players';

function ownRow(
  rows: RegistryRowDTO[],
  displayName: string,
  color: string,
): RegistryRowDTO | null {
  const wanted = color.toLowerCase();
  return (
    rows.find((row) => {
      const cell = row.cells['nation'];
      return (
        isNationCell(cell) &&
        cell.name === displayName &&
        cell.color.toLowerCase() === wanted
      );
    }) ?? null
  );
}

function statOf(row: RegistryRowDTO, column: string): number | null {
  const cell = row.cells[column];
  return typeof cell === 'number' ? cell : null;
}

export function useOwnStats(nation: NationDTO): OwnStatsState {
  const { token } = useSession();
  const [state, setState] = useState<OwnStatsState>({
    status: 'loading',
    stats: null,
  });
  // The lookup keys — a fresh NationDTO after each save must not
  // refetch; only a changed name/colour can move the owner's row.
  const displayName = nation.short_name ?? nation.name;
  const color = nation.color_hex;

  useEffect(() => {
    const controller = new AbortController();
    registryApi
      .getRows(token, PLAYERS_TABLE_ID, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) {
          return;
        }
        const row = ownRow(data.rows, displayName, color);
        setState({
          status: 'ready',
          stats:
            row === null
              ? null
              : {
                  level: statOf(row, 'level'),
                  judgeRating: statOf(row, 'judge_rating'),
                },
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setState({
          status: 'error',
          stats: null,
          error:
            error instanceof Error ? error : new Error('Неизвестная ошибка'),
        });
      });
    return () => controller.abort();
  }, [token, displayName, color]);

  return state;
}
