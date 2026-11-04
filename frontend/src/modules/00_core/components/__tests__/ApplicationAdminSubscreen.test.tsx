/**
 * ApplicationAdminSubscreen — the administrator's review window
 * (Spec applications §10, mockups 21/21b/21c/21d; jsdom; network via
 * msw): the PENDING facts card and decision bar, the 21d state lines,
 * the return dialog's empty/422/OK comment path and the silent
 * reload on a raced decision (409/403).
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import type { AdminApplicationDTO } from '../../../../shared/types';
import { ApplicationAdminSubscreen } from '../ApplicationAdminSubscreen';
import {
  APPLICATION_PENDING,
  registerDefaultHandlers,
  renderWithProviders,
  RULES,
  SESSION,
} from './helpers';

const APP_ID = 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d';

const ADMIN_APPLICATION: AdminApplicationDTO = {
  ...APPLICATION_PENDING,
  // A deadline relative to now keeps «осталось …» deterministic.
  review_deadline_at: new Date(Date.now() + (21 * 60 + 40) * 60_000).toISOString(),
  id: APP_ID,
  owner_vk_user_id: 987654,
  owner_name: 'Иван Петров',
  submitted_at: '2026-10-31T11:20:00Z',
  decided_at: null,
  auto_accepted: null,
  accepted_nation_id: null,
  images: {
    flag: { url: '/api/v1/images/flag-full', thumb_url: '/api/v1/images/flag-thumb' },
    portrait: {
      url: '/api/v1/images/portrait-full',
      thumb_url: '/api/v1/images/portrait-thumb',
    },
  },
};

function adminGet(body: () => AdminApplicationDTO | Response) {
  return http.get(`*/api/v1/admin/applications/${APP_ID}`, () => {
    const answer = body();
    return answer instanceof Response ? answer : HttpResponse.json(answer);
  });
}

const renderSubscreen = (onBack = vi.fn()) =>
  renderWithProviders(
    <ApplicationAdminSubscreen applicationId={APP_ID} onBack={onBack} />,
  );

beforeEach(registerDefaultHandlers);

describe('ApplicationAdminSubscreen — the PENDING window', () => {
  it('shows the facts, the blocks and the decision bar (mockup 21)', async () => {
    server.use(adminGet(() => HttpResponse.json(ADMIN_APPLICATION)));
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(within(facts).getByText('Анкета государства')).toBeInTheDocument();
    expect(within(facts).getByText('Testia')).toBeInTheDocument();
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('На рассмотрении');
    expect(facts).toHaveTextContent('Иван Петров · id 987654');
    // 2026-10-31T11:20Z → «31 октября, 14:20» in the tick zone.
    expect(facts).toHaveTextContent('31 октября, 14:20');
    expect(facts).toHaveTextContent('отправка №1');
    expect(facts).toHaveTextContent('осталось');
    // 13b: no assigned reviewer — the mark is gone for everyone.
    expect(facts).not.toHaveTextContent('Рецензент');
    expect(facts).not.toHaveTextContent('назначена вам');

    // The application blocks with the admin's delete buttons.
    expect(
      screen.getByTestId('delete-flag'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('delete-portrait'),
    ).toBeInTheDocument();

    // The sticky bar of mockup 21.
    const bar = screen.getByTestId('application-admin-actions');
    expect(
      within(bar).getByTestId('open-return-application'),
    ).toBeInTheDocument();
    expect(
      within(bar).getByTestId('open-accept-application'),
    ).toBeInTheDocument();
    expect(bar).toHaveTextContent('Свою анкету рассматривать нельзя.');
  });
});

describe('ApplicationAdminSubscreen — the 21d states', () => {
  it('withdrawn by the player: «Отозвана игроком», no decision buttons', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json({
          ...ADMIN_APPLICATION,
          status: 'DRAFT',
          draft_reason: 'cancelled',
          submitted_at: null,
          review_deadline_at: null,
        }),
      ),
    );
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('Отозвана игроком');
    expect(facts).toHaveTextContent('Игрок отменил анкету');
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });

  it('accepted by another administrator: «Принята» + the stamp', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json({
          ...ADMIN_APPLICATION,
          status: 'ACCEPTED',
          decided_at: '2026-10-31T13:12:00Z',
          auto_accepted: false,
          accepted_nation_id: 'nation-1',
        }),
      ),
    );
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('Принята');
    expect(facts).toHaveTextContent('Анкета принята 31 октября, 16:12');
    expect(facts).toHaveTextContent('Государство создано.');
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });

  it('auto-accepted: «Принята автоматически» with the review_hours text', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json({
          ...ADMIN_APPLICATION,
          status: 'ACCEPTED',
          decided_at: '2026-11-01T11:20:00Z',
          auto_accepted: true,
          accepted_nation_id: 'nation-1',
        }),
      ),
    );
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('Принята автоматически');
    // review_hours comes from GET /nations/rules (30 in the fixture —
    // a hardcoded 24 would fail).
    expect(facts).toHaveTextContent(
      `Решения не было ${RULES.application.review_hours} часов`,
    );
    expect(facts).toHaveTextContent('принята «как есть» 1 ноября, 14:20');
  });

  it('returned by another administrator: «Возвращена» + the comment', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json({
          ...ADMIN_APPLICATION,
          status: 'DRAFT',
          draft_reason: 'returned',
          return_comment: 'Ссылка на историю ведёт на пустую страницу.',
          submitted_at: null,
          review_deadline_at: null,
        }),
      ),
    );
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('Возвращена');
    expect(facts).toHaveTextContent(
      '«Ссылка на историю ведёт на пустую страницу.»',
    );
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });

  it('own application: the note, no decision buttons', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json({
          ...ADMIN_APPLICATION,
          owner_vk_user_id: SESSION.player.vk_user_id,
        }),
      ),
    );
    renderSubscreen();

    const facts = await screen.findByTestId('application-admin-facts');
    expect(
      within(facts).getByTestId('application-admin-state'),
    ).toHaveTextContent('На рассмотрении');
    expect(facts).toHaveTextContent(
      'Свою анкету рассматривать нельзя',
    );
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });
});

describe('ApplicationAdminSubscreen — decisions', () => {
  it('«Вернуть с причиной»: empty stays off, a 422 shows the error, a good comment returns the draft', async () => {
    let badComment = true;
    let posts = 0;
    const returned: AdminApplicationDTO = {
      ...ADMIN_APPLICATION,
      status: 'DRAFT',
      draft_reason: 'returned',
      return_comment: 'Причина.',
      submitted_at: null,
      review_deadline_at: null,
    };
    server.use(
      adminGet(() => HttpResponse.json(ADMIN_APPLICATION)),
      http.post(`*/api/v1/admin/applications/${APP_ID}/return`, () => {
        posts += 1;
        return badComment
          ? HttpResponse.json(
              { detail: 'bad comment', code: 'RETURN_COMMENT_INVALID' },
              { status: 422 },
            )
          : HttpResponse.json(returned);
      }),
    );
    renderSubscreen();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('open-return-application'));
    const popup = await screen.findByTestId('popup-return-application');
    const confirm = within(popup).getByTestId('confirm-return-application');
    expect(confirm).toBeDisabled();

    await user.type(
      within(popup).getByLabelText('Причина возврата'),
      'Плохая причина',
    );
    // The counter uses comment_max_length from GET /nations/rules.
    expect(popup).toHaveTextContent(
      `14 / ${RULES.application.comment_max_length}`,
    );
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    // The 422 shows the field error inside the same dialog.
    await waitFor(() =>
      expect(within(popup).getByText('Укажите причину возврата.')).toBeInTheDocument(),
    );
    expect(posts).toBe(1);

    // A good comment returns the application — the plate flips.
    badComment = false;
    await user.click(
      within(popup).getByTestId('confirm-return-application'),
    );
    await waitFor(() => expect(posts).toBe(2));
    const facts = await screen.findByTestId('application-admin-facts');
    await waitFor(() =>
      expect(
        within(facts).getByTestId('application-admin-state'),
      ).toHaveTextContent('Возвращена'),
    );
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });

  it('«Принять анкету» confirms in the S popup and the plate flips to «Принята»', async () => {
    let posts = 0;
    const accepted: AdminApplicationDTO = {
      ...ADMIN_APPLICATION,
      status: 'ACCEPTED',
      decided_at: '2026-11-03T10:00:00Z',
      auto_accepted: false,
      accepted_nation_id: 'nation-1',
    };
    server.use(
      adminGet(() => HttpResponse.json(ADMIN_APPLICATION)),
      http.post(`*/api/v1/admin/applications/${APP_ID}/accept`, () => {
        posts += 1;
        return HttpResponse.json(accepted);
      }),
    );
    renderSubscreen();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('open-accept-application'));
    const popup = await screen.findByTestId('popup-accept-application');
    expect(popup).toHaveTextContent(
      'Будет создано государство «Testia».',
    );
    expect(popup).toHaveTextContent('3 провинции закрепятся за ним');
    expect(popup).toHaveTextContent(
      'Решение записывается в журнал администратора.',
    );

    await user.click(
      within(popup).getByTestId('confirm-accept-application'),
    );
    await waitFor(() => expect(posts).toBe(1));
    const facts = await screen.findByTestId('application-admin-facts');
    await waitFor(() =>
      expect(
        within(facts).getByTestId('application-admin-state'),
      ).toHaveTextContent('Принята'),
    );
    expect(
      screen.queryByTestId('application-admin-actions'),
    ).not.toBeInTheDocument();
  });

  it('a 409 on accept reloads the window and shows the new state — no error stack', async () => {
    const returned: AdminApplicationDTO = {
      ...ADMIN_APPLICATION,
      status: 'DRAFT',
      draft_reason: 'returned',
      return_comment: 'Вернули раньше.',
      submitted_at: null,
      review_deadline_at: null,
    };
    server.use(
      adminGet(() => HttpResponse.json(ADMIN_APPLICATION)),
      http.post(`*/api/v1/admin/applications/${APP_ID}/accept`, () =>
        HttpResponse.json(
          {
            detail: 'Application is not under review (current status DRAFT)',
            code: 'APPLICATION_NOT_PENDING',
            details: { status: 'DRAFT' },
          },
          { status: 409 },
        ),
      ),
    );
    renderSubscreen();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('open-accept-application'));
    const popup = await screen.findByTestId('popup-accept-application');
    // The next GET answers the decided application.
    server.use(adminGet(() => HttpResponse.json(returned)));
    await user.click(
      within(popup).getByTestId('confirm-accept-application'),
    );

    const facts = await screen.findByTestId('application-admin-facts');
    await waitFor(() =>
      expect(
        within(facts).getByTestId('application-admin-state'),
      ).toHaveTextContent('Возвращена'),
    );
    expect(facts).toHaveTextContent('«Вернули раньше.»');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('popup-accept-application'),
    ).not.toBeInTheDocument();
  });
});

describe('ApplicationAdminSubscreen — image delete and fallbacks', () => {
  it('«Удалить флаг» confirms, then POSTs and the button is gone', async () => {
    let deletes = 0;
    server.use(
      adminGet(() => HttpResponse.json(ADMIN_APPLICATION)),
      http.post(
        `*/api/v1/admin/applications/${APP_ID}/images/flag/delete`,
        () => {
          deletes += 1;
          return HttpResponse.json({
            ...ADMIN_APPLICATION,
            images: { ...ADMIN_APPLICATION.images, flag: null },
          });
        },
      ),
    );
    renderSubscreen();
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('delete-flag'));
    const popup = await screen.findByTestId('popup-delete-image');
    await user.click(within(popup).getByTestId('confirm-delete-image'));

    await waitFor(() => expect(deletes).toBe(1));
    await waitFor(() =>
      expect(screen.queryByTestId('delete-flag')).not.toBeInTheDocument(),
    );
    // The portrait button stays.
    expect(screen.getByTestId('delete-portrait')).toBeInTheDocument();
  });

  it('a 404 APPLICATION_NOT_FOUND shows the empty state, a 403 sends back with no error', async () => {
    server.use(
      adminGet(() =>
        HttpResponse.json(
          { detail: 'no such application', code: 'APPLICATION_NOT_FOUND' },
          { status: 404 },
        ),
      ),
    );
    const onBack404 = vi.fn();
    renderWithProviders(
      <ApplicationAdminSubscreen applicationId={APP_ID} onBack={onBack404} />,
    );
    expect(await screen.findByText('Анкета не найдена')).toBeInTheDocument();
    expect(onBack404).not.toHaveBeenCalled();

    server.use(
      adminGet(() =>
        HttpResponse.json(
          { detail: 'not an admin', code: 'ADMIN_REQUIRED' },
          { status: 403 },
        ),
      ),
    );
    const onBack403 = vi.fn();
    renderWithProviders(
      <ApplicationAdminSubscreen applicationId={APP_ID} onBack={onBack403} />,
    );
    await waitFor(() => expect(onBack403).toHaveBeenCalled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
