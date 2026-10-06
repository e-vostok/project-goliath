/**
 * useBotStatus — the single GET /bot/status per app start and the
 * fail-open normalization (INV-B15): any failure or malformed payload
 * must land on 'unavailable'/'disabled', never on a blocking state.
 */

import { renderHook, waitFor } from '@testing-library/react';
import { HttpResponse } from 'msw';

import { useBotStatus } from '../hooks/useBotStatus';
import {
  botHookWrapper,
  botStatusReady,
  CHAT_URL,
  mswBot,
  registerBotHandlers,
} from './helpers';

beforeEach(registerBotHandlers);

describe('useBotStatus', () => {
  it('enabled=false resolves to disabled', async () => {
    const { result } = renderHook(() => useBotStatus(), {
      wrapper: botHookWrapper,
    });
    expect(result.current.state.status).toBe('loading');
    await waitFor(() =>
      expect(result.current.state.status).toBe('disabled'),
    );
    expect(mswBot.statusCalls).toBe(1);
  });

  it('a healthy DTO resolves to ready with the server body', async () => {
    mswBot.status = () => HttpResponse.json(botStatusReady());
    const { result } = renderHook(() => useBotStatus(), {
      wrapper: botHookWrapper,
    });
    await waitFor(() =>
      expect(result.current.state.status).toBe('ready'),
    );
    const state = result.current.state;
    if (state.status !== 'ready') {
      throw new Error('unreachable — narrowed above');
    }
    expect(state.dto.chat_url).toBe(CHAT_URL);
    expect(state.dto.consent_poll_interval_seconds).toBeGreaterThan(0);
  });

  it.each([
    ['HTTP 500', () => HttpResponse.json(
      { detail: 'boom', code: 'INTERNAL' },
      { status: 500 },
    )],
    ['network error', () => HttpResponse.error()],
  ])('%s resolves to unavailable', async (_name, handler) => {
    mswBot.status = handler;
    const { result } = renderHook(() => useBotStatus(), {
      wrapper: botHookWrapper,
    });
    await waitFor(() =>
      expect(result.current.state.status).toBe('unavailable'),
    );
  });

  it.each([
    ['http://', 'http://vk.com/write-1'],
    ['javascript:', 'javascript:alert(1)'],
    ['null while enabled', null],
  ])('chat_url %s is treated as unavailable', async (_name, chatUrl) => {
    mswBot.status = () =>
      HttpResponse.json(
        botStatusReady({ chat_url: chatUrl as string | null }),
      );
    const { result } = renderHook(() => useBotStatus(), {
      wrapper: botHookWrapper,
    });
    await waitFor(() =>
      expect(result.current.state.status).toBe('unavailable'),
    );
  });

  it('fires exactly one GET per app start — no refetch on re-render', async () => {
    const { result, rerender } = renderHook(() => useBotStatus(), {
      wrapper: botHookWrapper,
    });
    await waitFor(() =>
      expect(result.current.state.status).toBe('disabled'),
    );
    rerender();
    rerender();
    await waitFor(() => expect(mswBot.statusCalls).toBe(1));
  });
});
