/**
 * BotConsentRow — the «Уведомления» line on the nation screen (Spec 5.6).
 *
 * ALLOWED → «Включены»; DENIED/UNKNOWN → «Выключены» + «Включить в чате»
 * with the same consent polling as the gate; hidden entirely when the
 * bot is disabled, the status failed, or stale+UNKNOWN. The consent gate
 * never appears for a player who already owns a nation.
 */

import { act, fireEvent, screen } from '@testing-library/react';
import { HttpResponse } from 'msw';

import {
  registerDefaultHandlers,
  SESSION,
} from '../../00_core/components/__tests__/helpers';
import { PanelNationHome } from '../../00_core/components/PanelNationHome';
import type { NationDTO } from '../../../shared/types';
import { BOT_TEXTS } from '../texts';
import {
  botStatusReady,
  BOT_STATUS_DISABLED,
  CHAT_URL,
  mswBot,
  POLL_INTERVAL_SECONDS,
  registerBotHandlers,
  renderWithBot,
  usePollingTimers,
} from './helpers';

const NATION: NationDTO = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  name: 'Testia',
  color_hex: '#e64545',
  owner_player_id: SESSION.player.id,
  province_ids: [1, 2],
  leader_name: 'Иван Грозный',
  leader_title: 'Верховный правитель',
  history_url: 'https://vk.com/@testia-istoriya',
  created_at: '2026-09-27T00:00:00Z',
};

function renderHome() {
  renderWithBot(
    <PanelNationHome
      nation={NATION}
      onChanged={vi.fn()}
      onDeleteRequest={vi.fn()}
    />,
  );
}

async function flushAsync() {
  await act(async () => {
    await new Promise((resolve) => {
      setImmediate(resolve);
    });
  });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await flushAsync();
}

beforeEach(() => {
  registerDefaultHandlers();
  registerBotHandlers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('BotConsentRow — visibility and states', () => {
  it('ALLOWED → «Включены», no chat link', async () => {
    mswBot.status = () =>
      HttpResponse.json(botStatusReady({ consent: 'ALLOWED' }));
    renderHome();
    expect(await screen.findByText(BOT_TEXTS.rowOn)).toBeInTheDocument();
    expect(screen.getByText(BOT_TEXTS.rowLabel)).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: BOT_TEXTS.rowEnable }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(BOT_TEXTS.gateTitle)).not.toBeInTheDocument();
  });

  it.each([
    ['DENIED', 'DENIED'],
    ['UNKNOWN', 'UNKNOWN'],
  ] as const)(
    '%s → «Выключены» + «Включить в чате»; a nation owner never sees the gate',
    async (_name, consent) => {
      mswBot.status = () => HttpResponse.json(botStatusReady({ consent }));
      renderHome();
      expect(
        await screen.findByText(BOT_TEXTS.rowOff),
      ).toBeInTheDocument();
      const link = screen.getByRole('link', { name: BOT_TEXTS.rowEnable });
      expect(link).toHaveAttribute('href', CHAT_URL);
      expect(link).toHaveAttribute('target', '_blank');
      expect(link.getAttribute('rel')).toContain('noopener noreferrer');
      expect(screen.queryByText(BOT_TEXTS.gateTitle)).not.toBeInTheDocument();
    },
  );

  it.each([
    ['disabled', () => HttpResponse.json(BOT_STATUS_DISABLED)],
    [
      'status request failed',
      () =>
        HttpResponse.json(
          { detail: 'boom', code: 'INTERNAL' },
          { status: 500 },
        ),
    ],
    [
      'stale + UNKNOWN',
      () => HttpResponse.json(botStatusReady({ stale: true })),
    ],
  ])('row hidden when %s', async (_name, handler) => {
    mswBot.status = handler;
    renderHome();
    // The rest of the screen renders; the row never appears.
    await screen.findByText('Иван Грозный');
    expect(screen.queryByText(BOT_TEXTS.rowLabel)).not.toBeInTheDocument();
  });
});

describe('BotConsentRow — enable flow', () => {
  it('link click starts polling; ALLOWED flips the row to «Включены»', async () => {
    let allowed = false;
    mswBot.status = () =>
      HttpResponse.json(botStatusReady({ consent: 'DENIED' }));
    mswBot.refresh = () =>
      HttpResponse.json(
        botStatusReady({ consent: allowed ? 'ALLOWED' : 'DENIED' }),
      );
    renderHome();
    const link = await screen.findByRole('link', {
      name: BOT_TEXTS.rowEnable,
    });

    usePollingTimers();
    fireEvent.click(link);
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(1);
    expect(screen.getByTestId('bot-row-waiting')).toBeInTheDocument();

    allowed = true;
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(2);
    vi.useRealTimers();
    await screen.findByText(BOT_TEXTS.rowOn);
    expect(
      screen.queryByRole('link', { name: BOT_TEXTS.rowEnable }),
    ).not.toBeInTheDocument();
  });

  it('timeout shows «Проверить ещё раз», which fires exactly one request', async () => {
    mswBot.status = () =>
      HttpResponse.json(
        botStatusReady({
          consent: 'DENIED',
          consent_poll_timeout_seconds: POLL_INTERVAL_SECONDS + 1,
        }),
      );
    renderHome();
    const link = await screen.findByRole('link', {
      name: BOT_TEXTS.rowEnable,
    });

    usePollingTimers();
    fireEvent.click(link);
    await advance(POLL_INTERVAL_SECONDS * 1000);
    await advance(1000);

    const recheck = screen.getByRole('button', {
      name: BOT_TEXTS.recheckButton,
    });
    const callsBefore = mswBot.refreshCalls;
    fireEvent.click(recheck);
    await flushAsync();
    expect(mswBot.refreshCalls).toBe(callsBefore + 1);
    expect(screen.getByText(BOT_TEXTS.rowOff)).toBeInTheDocument();
  });
});
