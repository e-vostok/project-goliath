/**
 * useAuth — the auth-gate hook.
 *
 * msw serves realistic Spec Part 5 responses: AuthResponseDTO on success,
 * ErrorResponse{detail, code} on failure (e.g. INVALID_SIGNATURE).
 */

import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { useAuth } from '../../hooks/useAuth';

const AUTH_URL = '*/api/v1/auth/vk';

const PLAYER = {
  id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
  vk_user_id: 123456,
  created_at: '2026-09-01T12:00:00Z',
};

describe('useAuth', () => {
  it('goes loading → authenticated and posts the launch params', async () => {
    window.history.pushState({}, '', '/?vk_user_id=123456&sign=deadbeef');

    let seenBody: unknown;
    server.use(
      http.post(AUTH_URL, async ({ request }) => {
        seenBody = await request.json();
        return HttpResponse.json(
          {
            access_token: 'jwt-token-abc',
            token_type: 'bearer',
            expires_in: 3600,
            player: PLAYER,
          },
          { status: 200 },
        );
      }),
    );

    const { result } = renderHook(() => useAuth());
    expect(result.current.status).toBe('loading');

    await waitFor(() =>
      expect(result.current.status).toBe('authenticated'),
    );
    expect(result.current).toMatchObject({
      token: 'jwt-token-abc',
      player: { vk_user_id: 123456 },
    });
    expect(seenBody).toEqual({
      launch_params: '?vk_user_id=123456&sign=deadbeef',
    });
  });

  it('goes loading → error when the backend rejects the signature', async () => {
    server.use(
      http.post(AUTH_URL, () =>
        HttpResponse.json(
          { detail: 'Invalid launch params signature', code: 'INVALID_SIGNATURE' },
          { status: 401 },
        ),
      ),
    );

    const { result } = renderHook(() => useAuth());
    expect(result.current.status).toBe('loading');

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(
      result.current.status === 'error' ? result.current.error : null,
    ).toMatchObject({ message: 'Invalid launch params signature' });
  });
});
