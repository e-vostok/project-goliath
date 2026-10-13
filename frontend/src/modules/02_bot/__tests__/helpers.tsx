/**
 * Shared helpers for 02_bot tests: the provider stack (Session +
 * BotStatusProvider), the default bot status DTOs and the mutable msw
 * handler state.
 *
 * Mirrors the 00_core helpers convention: the fixture deliberately uses
 * NON-backend-config numbers (interval 2s, timeout 8s — the real config
 * defaults are 3s/90s) so a hardcoded client value fails these tests.
 * Assertions must read the numbers from the fixture, not from the spec.
 */

import type { ReactElement, ReactNode } from 'react';
import { render } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';

import { server } from '../../../../vitest.setup';
import { SESSION } from '../../00_core/components/__tests__/helpers';
import { SessionProvider } from '../../00_core/hooks/useAuth';
import { BotStatusProvider } from '../hooks/useBotStatus';
import type { BotStatusDTO } from '../api';

export { SESSION };

/** Distinct from the real config defaults — a hardcoded client number fails. */
export const POLL_INTERVAL_SECONDS = 2;
export const POLL_TIMEOUT_SECONDS = 8;
export const CHAT_URL = 'https://vk.com/write-777000111';

export const BOT_STATUS_DISABLED: BotStatusDTO = {
  enabled: false,
  consent: 'UNKNOWN',
  stale: false,
  throttled: false,
  registration_requires_consent: false,
  chat_url: null,
  consent_poll_interval_seconds: null,
  consent_poll_timeout_seconds: null,
};

export function botStatusReady(
  overrides: Partial<BotStatusDTO> = {},
): BotStatusDTO {
  return {
    enabled: true,
    consent: 'UNKNOWN',
    stale: false,
    throttled: false,
    registration_requires_consent: true,
    chat_url: CHAT_URL,
    consent_poll_interval_seconds: POLL_INTERVAL_SECONDS,
    consent_poll_timeout_seconds: POLL_TIMEOUT_SECONDS,
    ...overrides,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type BotHandler = () => HttpResponse<any> | Promise<HttpResponse<any>>;

/**
 * Mutable bot fixture served by the msw handlers — tests replace
 * `status`/`refresh` per case and read the call counters.
 */
export const mswBot: {
  statusCalls: number;
  refreshCalls: number;
  status: BotHandler;
  refresh: BotHandler;
} = {
  statusCalls: 0,
  refreshCalls: 0,
  status: () => HttpResponse.json(BOT_STATUS_DISABLED),
  refresh: () => HttpResponse.json(botStatusReady({ consent: 'DENIED' })),
};

export function resetMswBot() {
  mswBot.statusCalls = 0;
  mswBot.refreshCalls = 0;
  mswBot.status = () => HttpResponse.json(BOT_STATUS_DISABLED);
  mswBot.refresh = () => HttpResponse.json(botStatusReady({ consent: 'DENIED' }));
}

/** Call in beforeEach — registers GET /bot/status and POST consent/refresh. */
export function registerBotHandlers() {
  resetMswBot();
  server.use(
    http.get('*/api/v1/bot/status', () => {
      mswBot.statusCalls += 1;
      return mswBot.status();
    }),
    http.post('*/api/v1/bot/consent/refresh', () => {
      mswBot.refreshCalls += 1;
      return mswBot.refresh();
    }),
  );
}

const BotWrapper = ({ children }: { children: ReactNode }) => (
  <ConfigProvider platform={Platform.VKCOM}>
    <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
      <AppRoot>
        <SessionProvider session={SESSION}>
          <BotStatusProvider>{children}</BotStatusProvider>
        </SessionProvider>
      </AppRoot>
    </AdaptivityProvider>
  </ConfigProvider>
);

/** Renders inside the real BotStatusProvider — GET /bot/status fires once. */
export function renderWithBot(ui: ReactElement) {
  return render(<BotWrapper>{ui}</BotWrapper>);
}

/** Hook wrapper for renderHook — same provider stack. */
export const botHookWrapper = BotWrapper;

/**
 * Fake timers restricted to the APIs the polling loop uses —
 * setImmediate/nextTick stay real so msw responses still resolve.
 * userEvent is unusable under fake timers in this stack — clicks while
 * timers are faked go through `fireEvent.click` (synchronous).
 */
export function usePollingTimers() {
  vi.useFakeTimers({
    toFake: [
      'setTimeout',
      'clearTimeout',
      'setInterval',
      'clearInterval',
      'Date',
    ],
  });
}
