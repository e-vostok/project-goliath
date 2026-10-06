/**
 * Registration container × 02_bot (Spec Appendix B7).
 *
 * 403 CONSENT_REQUIRED on POST /nations must bring the consent gate
 * back without losing the entered values; once consent flips to
 * ALLOWED the same filled form returns. With the bot disabled the
 * container output is exactly the pre-Issue one.
 */

import { act, fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../vitest.setup';
import {
  fillStep1,
  fillStep2,
  registerDefaultHandlers,
} from '../../00_core/components/__tests__/helpers';
import { PanelCreateNation } from '../../00_core/components/PanelCreateNation';
import { BOT_TEXTS } from '../texts';
import {
  botStatusReady,
  BOT_STATUS_DISABLED,
  mswBot,
  POLL_INTERVAL_SECONDS,
  registerBotHandlers,
  renderWithBot,
  usePollingTimers,
} from './helpers';

beforeEach(() => {
  registerDefaultHandlers();
  registerBotHandlers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('PanelCreateNation — CONSENT_REQUIRED', () => {
  it('submit → 403 returns to the gate, then ALLOWED restores the filled form', async () => {
    // Consent looked ALLOWED at status time, so the form opened; the
    // server re-check on submit still refuses — the gate must come back.
    mswBot.status = () =>
      HttpResponse.json(botStatusReady({ consent: 'ALLOWED' }));
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'Message consent required', code: 'CONSENT_REQUIRED' },
          { status: 403 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithBot(<PanelCreateNation onCreated={vi.fn()} />);
    await screen.findByLabelText('Название государства');
    await fillStep1(user);
    await fillStep2(user);
    await user.click(
      screen.getByRole('button', { name: /основать государство/i }),
    );

    // The gate replaces the form; entered values stay in the container.
    await screen.findByText(BOT_TEXTS.gateTitle);

    mswBot.refresh = () =>
      HttpResponse.json(botStatusReady({ consent: 'ALLOWED' }));
    usePollingTimers();
    fireEvent.click(
      screen.getByRole('link', { name: BOT_TEXTS.gateButton }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_SECONDS * 1000);
    });
    await act(async () => {
      await new Promise((resolve) => {
        setImmediate(resolve);
      });
    });
    vi.useRealTimers();

    // ALLOWED — the form returns on the same step with the same values.
    expect(
      await screen.findByLabelText('Ссылка на историю государства'),
    ).toHaveValue('https://vk.com/@testia-istoriya');
    fireEvent.click(screen.getByTestId('step-prev'));
    expect(screen.getByLabelText('Название государства')).toHaveValue(
      'Testia',
    );
    expect(screen.getByLabelText('Имя лидера')).toHaveValue('Иван Грозный');
    expect(screen.getByLabelText('Должность лидера')).toHaveValue(
      'Верховный правитель',
    );
  });

  it('403 CONSENT_REQUIRED with a previously failed status refetches status once and shows the gate', async () => {
    // First status request fails (form opens, fail-open) — the explicit
    // server refusal must still reach the gate via a single retry.
    let attempts = 0;
    mswBot.status = () => {
      attempts += 1;
      return attempts === 1
        ? HttpResponse.error()
        : HttpResponse.json(botStatusReady({ consent: 'UNKNOWN' }));
    };
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(
          { detail: 'Message consent required', code: 'CONSENT_REQUIRED' },
          { status: 403 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithBot(<PanelCreateNation onCreated={vi.fn()} />);
    await screen.findByLabelText('Название государства');
    await fillStep1(user);
    await fillStep2(user);
    await user.click(
      screen.getByRole('button', { name: /основать государство/i }),
    );

    await screen.findByText(BOT_TEXTS.gateTitle);
    expect(mswBot.statusCalls).toBe(2);
  });

  it('with the bot disabled the container renders its pre-Issue output', async () => {
    mswBot.status = () => HttpResponse.json(BOT_STATUS_DISABLED);
    renderWithBot(<PanelCreateNation onCreated={vi.fn()} />);
    await screen.findByLabelText('Название государства');
    expect(screen.queryByText(BOT_TEXTS.gateTitle)).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /основать государство/i }),
    ).toBeInTheDocument();
  });
});
