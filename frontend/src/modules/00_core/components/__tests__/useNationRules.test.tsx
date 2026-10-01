/**
 * useNationRules — the GET /nations/rules lifecycle: loading → ready with
 * the server body, and a non-blocking error state on failure.
 */

import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { ApiError } from '../../../../shared/api-client';
import { SessionProvider } from '../../hooks/useAuth';
import { useNationRules } from '../../hooks/useNationRules';
import { registerDefaultHandlers, RULES, SESSION } from './helpers';

const wrapper = ({ children }: { children: ReactNode }) => (
  <SessionProvider session={SESSION}>{children}</SessionProvider>
);

beforeEach(registerDefaultHandlers);

describe('useNationRules', () => {
  it('goes loading → ready with the server body', async () => {
    const { result } = renderHook(() => useNationRules(), { wrapper });
    expect(result.current.status).toBe('loading');
    expect(result.current.rules).toBeNull();

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.rules).toEqual(RULES);
  });

  it('exposes an error state on HTTP 500', async () => {
    server.use(
      http.get('*/api/v1/nations/rules', () =>
        HttpResponse.json(
          { detail: 'boom', code: 'INTERNAL' },
          { status: 500 },
        ),
      ),
    );
    const { result } = renderHook(() => useNationRules(), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.rules).toBeNull();
    if (result.current.status !== 'error') {
      throw new Error('unreachable — narrowed above');
    }
    expect(result.current.error).toBeInstanceOf(ApiError);
  });
});
