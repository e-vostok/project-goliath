/**
 * PanelBotGate — the consent gate in front of the registration form.
 *
 * Covers the visibility matrix (Spec 5.6 + INV-B15 fail-open), the
 * new-tab chat anchor, the consent polling at server-given interval /
 * timeout, the visibility-return extra check, unmount cleanup and the
 * 409 BOT_DISABLED escape.
 *
 * Rendered through the real PanelCreateNation + BotStatusProvider so the
 * whole «status → gate → form» chain is exercised.
 */

import { act, fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse } from 'msw';

import { registerDefaultHandlers } from '../../00_core/components/__tests__/helpers';
import { PanelCreateNation } from '../../00_core/components/PanelCreateNation';
import { BOT_TEXTS } from '../texts';
import {
  botStatusReady,
  BOT_STATUS_DISABLED,
  CHAT_URL,
  mswBot,
  POLL_INTERVAL_SECONDS,
  POLL_TIMEOUT_SECONDS,
  registerBotHandlers,
  renderWithBot,
  usePollingTimers,
} from './helpers';

const GATE_TITLE = BOT_TEXTS.gateTitle;
const gate = () => screen.queryByText(GATE_TITLE);
const formField = () => screen.queryByLabelText('Название государства');
const chatLink = () =>
  screen.getByRole('link', { name: BOT_TEXTS.gateButton });

async function renderCreate() {
  renderWithBot(<PanelCreateNation onCreated={vi.fn()} />);
}

/** Gate shown with consent UNKNOWN. */
async function renderGate() {
  mswBot.status = () =>
    HttpResponse.json(botStatusReady({ consent: 'UNKNOWN' }));
  await renderCreate();
  await screen.findByText(GATE_TITLE);
}

/** One real event-loop turn inside act — drains the msw/fetch chain. */
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

describe('PanelBotGate — visibility matrix', () => {
  it.each([
    ['UNKNOWN consent', botStatusReady({ consent: 'UNKNOWN' }), true],
    ['DENIED consent', botStatusReady({ consent: 'DENIED' }), true],
    ['ALLOWED consent', botStatusReady({ consent: 'ALLOWED' }), false],
    [
      'registration_requires_consent=false',
      botStatusReady({ registration_requires_consent: false }),
      false,
    ],
    [
      'stale + UNKNOWN (fail-open)',
      botStatusReady({ stale: true, consent: 'UNKNOWN' }),
      false,
    ],
    [
      'stale + DENIED',
      botStatusReady({ stale: true, consent: 'DENIED' }),
      true,
    ],
    ['bot disabled', BOT_STATUS_DISABLED, false],
  ])('%s → gate: %s', async (_name, dto, expectGate) => {
    mswBot.status = () => HttpResponse.json(dto);
    await renderCreate();

    if (expectGate) {
      await screen.findByText(GATE_TITLE);
      expect(formField()).not.toBeInTheDocument();
    } else {
      await screen.findByLabelText('Название государства');
      expect(gate()).not.toBeInTheDocument();
    }
  });

  it.each([
    [
      'HTTP 500',
      () =>
        HttpResponse.json(
          { detail: 'boom', code: 'INTERNAL' },
          { status: 500 },
        ),
    ],
    ['network error', () => HttpResponse.error()],
  ])('status request fails (%s) → form, no gate (fail-open)', async (_n, handler) => {
    mswBot.status = handler;
    await renderCreate();
    await screen.findByLabelText('Название государства');
    expect(gate()).not.toBeInTheDocument();
  });

  it('shows the container loading state while the first status request is in flight — no form flash', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let release: (r: HttpResponse<any>) => void = () => {};
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const pending = new Promise<HttpResponse<any>>((resolve) => {
      release = resolve;
    });
    mswBot.status = () => pending;
    await renderCreate();

    await act(async () => {});
    expect(formField()).not.toBeInTheDocument();
    expect(gate()).not.toBeInTheDocument();

    release(HttpResponse.json(BOT_STATUS_DISABLED));
    await screen.findByLabelText('Название государства');
  });
});

describe('PanelBotGate — chat link', () => {
  it('is a plain new-tab anchor and never navigates the app', async () => {
    await renderGate();
    const link = chatLink();
    expect(link).toHaveAttribute('href', CHAT_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('rel')).toContain('noreferrer');

    const before = window.location.href;
    await userEvent.click(link);
    expect(window.location.href).toBe(before);
    expect(gate()).toBeInTheDocument();
  });
});

describe('PanelBotGate — consent polling', () => {

  it('starts polling at the server-given interval after the link click', async () => {
    await renderGate();
    usePollingTimers();
    expect(mswBot.refreshCalls).toBe(0);

    fireEvent.click(chatLink());
    expect(screen.getByTestId('bot-gate-waiting')).toBeInTheDocument();
    expect(mswBot.refreshCalls).toBe(0);

    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(1);
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(2);
  });

  it('stops polling and opens the form once consent is ALLOWED', async () => {
    let allowed = false;
    mswBot.refresh = () =>
      HttpResponse.json(
        botStatusReady({ consent: allowed ? 'ALLOWED' : 'DENIED' }),
      );
    await renderGate();
    usePollingTimers();
    fireEvent.click(chatLink());

    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(1);
    expect(gate()).toBeInTheDocument();

    allowed = true;
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(2);

    // Polling stopped — the deadline and further intervals fire nothing.
    await advance(POLL_INTERVAL_SECONDS * 1000 * 4);
    expect(mswBot.refreshCalls).toBe(2);

    vi.useRealTimers();
    await screen.findByLabelText('Название государства');
    expect(gate()).not.toBeInTheDocument();
  });

  it('ignores throttled answers and failed polls — keeps waiting', async () => {
    let n = 0;
    mswBot.refresh = () => {
      n += 1;
      if (n === 1) {
        return HttpResponse.json(botStatusReady({ throttled: true }));
      }
      if (n === 2) {
        return HttpResponse.error();
      }
      return HttpResponse.json(botStatusReady({ consent: 'DENIED' }));
    };
    await renderGate();
    usePollingTimers();
    fireEvent.click(chatLink());

    await advance(POLL_INTERVAL_SECONDS * 1000 * 3);
    expect(mswBot.refreshCalls).toBe(3);
    expect(screen.getByTestId('bot-gate-waiting')).toBeInTheDocument();
    expect(gate()).toBeInTheDocument();
  });

  it('times out after the server-given timeout; «Проверить ещё раз» fires exactly one request', async () => {
    // A timeout not divisible by the interval keeps call counts exact.
    mswBot.status = () =>
      HttpResponse.json(
        botStatusReady({
          consent: 'UNKNOWN',
          consent_poll_timeout_seconds:
            POLL_INTERVAL_SECONDS * 4 + 1,
        }),
      );
    await renderCreate();
    await screen.findByText(GATE_TITLE);
    usePollingTimers();
    fireEvent.click(chatLink());

    await advance(POLL_INTERVAL_SECONDS * 1000 * 4);
    expect(mswBot.refreshCalls).toBe(4);
    await advance(1000);
    expect(
      screen.getByText(BOT_TEXTS.gateTimeout),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: BOT_TEXTS.recheckButton }),
    );
    await flushAsync();
    expect(mswBot.refreshCalls).toBe(5);
    // Still not allowed — the same message stays.
    expect(screen.getByText(BOT_TEXTS.gateTimeout)).toBeInTheDocument();
  });

  it('clicking the chat link in the timed-out state restarts polling', async () => {
    mswBot.status = () =>
      HttpResponse.json(
        botStatusReady({
          consent: 'UNKNOWN',
          consent_poll_timeout_seconds: POLL_INTERVAL_SECONDS + 1,
        }),
      );
    await renderCreate();
    await screen.findByText(GATE_TITLE);
    usePollingTimers();
    fireEvent.click(chatLink());
    await advance(POLL_INTERVAL_SECONDS * 1000);
    await advance(1000);
    expect(
      screen.getByText(BOT_TEXTS.gateTimeout),
    ).toBeInTheDocument();

    const callsBefore = mswBot.refreshCalls;
    fireEvent.click(chatLink());
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(callsBefore + 1);
    expect(screen.getByTestId('bot-gate-waiting')).toBeInTheDocument();
  });

  it('fires one extra check when the tab becomes visible again — and none while not polling', async () => {
    await renderGate();

    // Not polling yet — a tab return must not call anything.
    fireVisibilityReturn();
    await act(async () => {});
    expect(mswBot.refreshCalls).toBe(0);

    usePollingTimers();
    fireEvent.click(chatLink());
    fireVisibilityReturn();
    await act(async () => {});
    expect(mswBot.refreshCalls).toBe(1);
  });

  it('clears all timers on unmount — no calls afterwards', async () => {
    mswBot.status = () =>
      HttpResponse.json(botStatusReady({ consent: 'UNKNOWN' }));
    const view = renderWithBot(<PanelCreateNation onCreated={vi.fn()} />);
    await screen.findByText(GATE_TITLE);
    usePollingTimers();
    fireEvent.click(chatLink());
    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(1);

    view.unmount();
    await advance(POLL_TIMEOUT_SECONDS * 2000);
    expect(mswBot.refreshCalls).toBe(1);
  });

  it('ends polling and opens the form on 409 BOT_DISABLED', async () => {
    mswBot.refresh = () =>
      HttpResponse.json(
        { detail: 'bot disabled', code: 'BOT_DISABLED' },
        { status: 409 },
      );
    await renderGate();
    usePollingTimers();
    fireEvent.click(chatLink());

    await advance(POLL_INTERVAL_SECONDS * 1000);
    expect(mswBot.refreshCalls).toBe(1);
    await advance(POLL_INTERVAL_SECONDS * 1000 * 5);
    expect(mswBot.refreshCalls).toBe(1);

    vi.useRealTimers();
    await screen.findByLabelText('Название государства');
    expect(gate()).not.toBeInTheDocument();
  });
});

function fireVisibilityReturn() {
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('focus'));
  });
}
