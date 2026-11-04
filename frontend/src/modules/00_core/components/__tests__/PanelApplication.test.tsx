/**
 * PanelApplication — the player's application window (Spec
 * applications §10, mockups 20/20b): the read-only status plate +
 * card blocks and the «Отменить анкету» confirm of size S.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import { PanelApplication } from '../PanelApplication';
import {
  APPLICATION_DRAFT,
  APPLICATION_PENDING,
  registerDefaultHandlers,
  renderWithProviders,
} from './helpers';

beforeEach(registerDefaultHandlers);

const renderPanel = (onChanged = vi.fn()) =>
  renderWithProviders(
    <PanelApplication
      application={APPLICATION_PENDING}
      onChanged={onChanged}
    />,
  );

describe('PanelApplication — the pending window', () => {
  it('shows the status plate and the whole application read-only', async () => {
    renderPanel();

    const plate = screen.getByTestId('application-status');
    expect(
      within(plate).getByText('Анкета · отправка №1'),
    ).toBeInTheDocument();
    expect(within(plate).getByText('На рассмотрении')).toBeInTheDocument();
    // 2026-11-02T11:20:00Z → «2 ноября, 14:20 (МСК)» in the tick zone.
    expect(plate).toHaveTextContent(
      'Решение будет принято не позже 2 ноября, 14:20 (МСК).',
    );
    expect(
      within(plate).getByRole('button', { name: 'Отменить анкету' }),
    ).toBeInTheDocument();

    // The card: names, leader, provinces capital-first, description,
    // the history link — nothing editable.
    expect(screen.getByText('Testia')).toBeInTheDocument();
    expect(screen.getByText('Иван Грозный')).toBeInTheDocument();
    const territory = screen.getByTestId('application-territory-block');
    const chips = within(territory)
      .getAllByText(/Эпсилон|Дзета|Эта/)
      .map((el) => el.textContent);
    expect(chips.length).toBe(3);
    expect(screen.queryByRole('textbox')).toBeNull();
  });

  it('«Отменить анкету» is the shared danger-outline button — red, not amber (13a)', async () => {
    renderPanel();

    const cancel = await screen.findByTestId('open-cancel-application');
    // The danger token on border AND text — the amber `signal` skin
    // is gone (mockup 20 renders «.btn do»).
    expect(cancel.style.border).toBe('1px solid var(--pax-danger)');
    expect(cancel.style.color).toBe('var(--pax-danger)');
    expect(cancel.style.border).not.toContain('signal');
    expect(cancel.style.background).toBe('transparent');
  });

  it('«Отменить анкету» asks, then POSTs cancel and reports back', async () => {
    let cancels = 0;
    server.use(
      http.post('*/api/v1/applications/me/cancel', () => {
        cancels += 1;
        return HttpResponse.json({
          ...APPLICATION_DRAFT,
          draft_reason: 'cancelled',
        });
      }),
    );
    const onChanged = vi.fn();
    renderPanel(onChanged);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole('button', { name: 'Отменить анкету' }),
    );
    const popup = await screen.findByTestId('popup-cancel-application');
    expect(
      within(popup).getByRole('button', { name: 'Не отменять' }),
    ).toBeInTheDocument();

    await user.click(
      within(popup).getByTestId('confirm-cancel-application'),
    );
    await waitFor(() => expect(cancels).toBe(1));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(
      screen.queryByTestId('popup-cancel-application'),
    ).not.toBeInTheDocument();
  });

  it('«Не отменять» closes the popup without a request', async () => {
    let cancels = 0;
    server.use(
      http.post('*/api/v1/applications/me/cancel', () => {
        cancels += 1;
        return HttpResponse.json(APPLICATION_DRAFT);
      }),
    );
    const onChanged = vi.fn();
    renderPanel(onChanged);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole('button', { name: 'Отменить анкету' }),
    );
    const popup = await screen.findByTestId('popup-cancel-application');
    await user.click(
      within(popup).getByRole('button', { name: 'Не отменять' }),
    );

    expect(
      screen.queryByTestId('popup-cancel-application'),
    ).not.toBeInTheDocument();
    expect(cancels).toBe(0);
    expect(onChanged).not.toHaveBeenCalled();
  });
});

describe('PanelApplication — the state changed elsewhere (audit of PR 267)', () => {
  it('a 409 APPLICATION_NOT_PENDING on cancel closes the popup and refreshes', async () => {
    // The application was already decided or cancelled elsewhere —
    // the popup closes and the shell refetches instead of an error.
    server.use(
      http.post('*/api/v1/applications/me/cancel', () =>
        HttpResponse.json(
          {
            detail: 'Application is not pending',
            code: 'APPLICATION_NOT_PENDING',
          },
          { status: 409 },
        ),
      ),
    );
    const onChanged = vi.fn();
    renderPanel(onChanged);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole('button', { name: 'Отменить анкету' }),
    );
    const popup = await screen.findByTestId('popup-cancel-application');
    await user.click(
      within(popup).getByTestId('confirm-cancel-application'),
    );

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(
      screen.queryByTestId('popup-cancel-application'),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
