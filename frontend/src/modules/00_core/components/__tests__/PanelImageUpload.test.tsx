/**
 * 0.12.0 unit 6b — image upload wired into the screens:
 * «Штаб» flag/portrait click → file input → replace-mode preview →
 * raw PUT /nations/me/images/{kind} → onChanged refresh; the Registry
 * nation subscreen keeps pictures read-only; registration keeps the
 * picked File in window state and sends flag-then-portrait AFTER
 * createNation, a failed PUT never cancels the creation.
 *
 * jsdom has no `createImageBitmap`/canvas — stubbed narrowly; the
 * picked "file" is a node:buffer Blob so undici streams it raw.
 */

import { Blob as NodeBlob } from 'node:buffer';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { server } from '../../../../../vitest.setup';
import type { NationDTO } from '../../../../shared/types';
import { PanelCreateNation } from '../PanelCreateNation';
import { PanelNationHome } from '../PanelNationHome';
import {
  goToTab,
  registerDefaultHandlers,
  renderWithProviders,
  seedRegistrationDraft,
  SESSION,
} from './helpers';

const NATION: NationDTO = {
  id: 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d',
  owner_player_id: SESSION.player.id,
  created_at: '2026-09-27T00:00:00Z',
  name: 'Testia',
  short_name: 'Тестия',
  color_hex: '#e64545',
  motto: null,
  description: null,
  flag_url: null,
  flag_thumb_url: null,
  province_ids: [1002, 1001],
  capital_province_id: 1001,
  capital_name: 'Столицево',
  leader_name: 'Иван Грозный',
  gender: 'male',
  leader_title: 'Верховный правитель',
  leader_bio: null,
  portrait_url: null,
  portrait_thumb_url: null,
  succession_type: 'elections',
  history_url: null,
  anthem_url: null,
  level: 5,
  judge_rating: 21,
};

function bitmap(width: number, height: number) {
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(async () => ({ width, height, close: () => {} }) as ImageBitmap),
  );
}

/** The file input of THIS slot — the button's own wrapper, not the
 * first input in the document (two slots render two inputs). */
function pickFile(slotButton: HTMLElement, file: File) {
  let host: HTMLElement | null = slotButton;
  let input: HTMLInputElement | null = null;
  while (host !== null && input === null) {
    input = host.querySelector('input[type="file"]');
    host = host.parentElement;
  }
  expect(input).not.toBeNull();
  fireEvent.change(input!, { target: { files: [file] } });
}

const pngFile = (name: string) =>
  new File(['PNG'], name, { type: 'image/png' });

/** A node:buffer Blob — undici (msw's fetch) streams it raw, unlike
 * jsdom's File which would stringify (test-env artifact, not prod). */
const rawPngFile = (name: string) =>
  Object.assign(new NodeBlob(['PNGDATA'], { type: 'image/png' }), {
    name,
  }) as unknown as File;

beforeEach(() => {
  registerDefaultHandlers();
  bitmap(1920, 1080);
  // jsdom's URL lacks the object-URL pair the registration window uses.
  (URL as unknown as Record<string, unknown>).createObjectURL = vi.fn(
    () => 'blob:mock',
  );
  (URL as unknown as Record<string, unknown>).revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('«Штаб» image upload', () => {
  it('flag click → file input → replace preview → raw PUT flag → onChanged', async () => {
    const seen: { body: string | null } = { body: null };
    server.use(
      http.put('*/api/v1/nations/me/images/flag', async ({ request }) => {
        seen.body = await request.text();
        return HttpResponse.json({
          kind: 'flag',
          url: '/i/a/full',
          thumb_url: '/i/a/thumb',
        });
      }),
    );
    const onChanged = vi.fn();
    const { container } = renderWithProviders(
      <PanelNationHome
        nation={NATION}
        onChanged={onChanged}
        onOpenRegistry={() => {}}
      />,
    );
    const user = userEvent.setup();

    // Stub shows «Загрузить флаг»; the click opens the hidden input.
    const slot = await screen.findByRole('button', {
      name: 'Загрузить флаг',
    });
    const input = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const clickSpy = vi.spyOn(input, 'click');
    await user.click(slot);
    expect(clickSpy).toHaveBeenCalled();

    // A valid file opens the replace-mode preview (real decode
    // stubbed); «Загрузить флаг» sends the raw PUT and refreshes.
    const file = rawPngFile('flag.png');
    pickFile(slot, file);
    const popup = await screen.findByTestId('popup-image-upload');
    expect(
      await screen.findByText(
        'Прежний флаг заменится новым и будет удалён с сервера.',
      ),
    ).toBeInTheDocument();
    await user.click(
      within(popup).getByRole('button', { name: 'Загрузить флаг' }),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    // The raw PUT body IS the File — same bytes, no wrapper.
    expect(seen.body).toBe(await file.text());
  });

  it('the portrait slot uploads through PUT .../images/portrait', async () => {
    const hits: string[] = [];
    server.use(
      http.put('*/api/v1/nations/me/images/portrait', () => {
        hits.push('portrait');
        return HttpResponse.json({
          kind: 'portrait',
          url: '/i/p/full',
          thumb_url: '/i/p/thumb',
        });
      }),
    );
    bitmap(800, 1000);
    const onChanged = vi.fn();
    renderWithProviders(
      <PanelNationHome
        nation={NATION}
        onChanged={onChanged}
        onOpenRegistry={() => {}}
      />,
    );
    const user = userEvent.setup();

    const slot = await screen.findByRole('button', {
      name: 'Загрузить портрет',
    });
    await user.click(slot);
    pickFile(slot, pngFile('portret.png'));
    const popup = await screen.findByTestId('popup-image-upload');
    await user.click(
      await within(popup).findByRole('button', {
        name: 'Загрузить портрет',
      }),
    );
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(hits).toEqual(['portrait']);
  });
});

describe('registration images', () => {
  const pickSlotFile = async (
    user: ReturnType<typeof userEvent.setup>,
    label: string,
    confirm: string,
    dims: { w: number; h: number } = { w: 1920, h: 1080 },
  ) => {
    bitmap(dims.w, dims.h);
    const slot = screen.getByRole('button', { name: label });
    await user.click(slot);
    pickFile(slot, pngFile('f.png'));
    const popup = await screen.findByTestId('popup-image-upload');
    await user.click(
      await within(popup).findByRole('button', { name: confirm }),
    );
  };

  it('a picked file stays in the window — nothing is sent before createNation', async () => {
    const calls: string[] = [];
    server.use(
      http.post('*/api/v1/nations', () => {
        calls.push('create');
        return HttpResponse.json(NATION, { status: 201 });
      }),
      http.put('*/api/v1/nations/me/images/flag', () => {
        calls.push('flag');
        return HttpResponse.json({ kind: 'flag', url: '/f', thumb_url: '/t' });
      }),
      http.put('*/api/v1/nations/me/images/portrait', () => {
        calls.push('portrait');
        return HttpResponse.json({
          kind: 'portrait',
          url: '/p',
          thumb_url: '/pt',
        });
      }),
    );
    seedRegistrationDraft();
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    // Tab 1 flag — «Использовать флаг» stores it, no request fires.
    await pickSlotFile(user, 'Загрузить флаг', 'Использовать флаг');
    expect(calls).toEqual([]);

    // Tab 2 portrait likewise (a vertical file — the check demands it).
    await goToTab(user, 2);
    await pickSlotFile(user, 'Загрузить портрет', 'Использовать портрет', {
      w: 800,
      h: 1000,
    });
    expect(calls).toEqual([]);

    // Submit: POST first, then flag, then portrait — in that order.
    await goToTab(user, 4);
    await user.click(
      await screen.findByRole('button', { name: 'Основать государство' }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(calls).toEqual(['create', 'flag', 'portrait']);
  });

  it('a failing flag PUT still ends in onCreated plus one danger notice', async () => {
    const calls: string[] = [];
    server.use(
      http.post('*/api/v1/nations', () => {
        calls.push('create');
        return HttpResponse.json(NATION, { status: 201 });
      }),
      http.put('*/api/v1/nations/me/images/flag', () => {
        calls.push('flag');
        return HttpResponse.json(
          { code: 'IMAGE_ORIENTATION_INVALID', detail: 'orient' },
          { status: 422 },
        );
      }),
    );
    seedRegistrationDraft();
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);

    await pickSlotFile(user, 'Загрузить флаг', 'Использовать флаг');
    await goToTab(user, 4);
    await user.click(
      await screen.findByRole('button', { name: 'Основать государство' }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(calls).toEqual(['create', 'flag']);
    // ONE notice slot — the danger message replaces the «Государство
    // создано» success one and carries the whole story itself.
    expect(
      await screen.findByText(
        /Государство создано, но флаг не загрузился/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId('notice')).toHaveLength(1);
  });

  it('registration with no pictures makes no PUT', async () => {
    const puts: string[] = [];
    server.use(
      http.post('*/api/v1/nations', () =>
        HttpResponse.json(NATION, { status: 201 }),
      ),
      http.put('*/api/v1/nations/me/images/*', () => {
        puts.push('put');
        return HttpResponse.json({});
      }),
    );
    seedRegistrationDraft();
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<PanelCreateNation onCreated={onCreated} />);
    await goToTab(user, 4);
    await user.click(
      await screen.findByRole('button', { name: 'Основать государство' }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(puts).toEqual([]);
  });
});
