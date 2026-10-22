/**
 * useGameClock — the top bar's clock source (unit 4a): null until the
 * first /game-clock answer, refetched whenever `refreshKey` changes
 * (AuthedArea feeds it `worldVersion` — the admin block's tick/reset).
 */

import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { SessionProvider } from '../../hooks/useAuth';
import { useGameClock } from '../../hooks/useGameClock';
import { GAME_CLOCK, SESSION } from './helpers';

const wrapper = ({ children }: { children: ReactNode }) => (
  <SessionProvider session={SESSION}>{children}</SessionProvider>
);

describe('useGameClock', () => {
  it('returns null until the answer, then the DTO; a refreshKey change refetches', async () => {
    let calls = 0;
    server.use(
      http.get('*/api/v1/game-clock', () => {
        calls += 1;
        return HttpResponse.json(GAME_CLOCK);
      }),
    );

    const { result, rerender } = renderHook(
      ({ key }: { key: number }) => useGameClock(key),
      { wrapper, initialProps: { key: 0 } },
    );
    expect(result.current).toBeNull();

    await waitFor(() => expect(result.current).toEqual(GAME_CLOCK));
    expect(calls).toBe(1);

    rerender({ key: 1 });
    await waitFor(() => expect(calls).toBe(2));
    expect(result.current).toEqual(GAME_CLOCK);
  });
});
