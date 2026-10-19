/**
 * useGameClock — GET /game-clock for the top bar's turn badge
 * (UI Spec 4). Fetches once per session token and again whenever the
 * `refreshKey` argument changes (AuthedArea passes `worldVersion`, so
 * the badge follows the admin block's tick/reset). Aborts on unmount.
 * Returns null until the first answer arrives — the badge is simply
 * not shown yet. PanelNationHome keeps its own clock fetch for now.
 */

import { useEffect, useState } from 'react';

import { api } from '../../../shared/api-client';
import type { GameClockDTO } from '../../../shared/types';
import { useSession } from './useAuth';

export function useGameClock(refreshKey: unknown = 0): GameClockDTO | null {
  const { token } = useSession();
  const [clock, setClock] = useState<GameClockDTO | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getGameClock(token, controller.signal)
      .then(setClock)
      .catch(() => {});
    return () => controller.abort();
  }, [token, refreshKey]);

  return clock;
}
