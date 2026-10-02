/**
 * PanelMap / MapView component tests (jsdom; network stubbed at the
 * fetch boundary with plain functions).
 *
 * Covered: node-path count matches the fixture, click→card with owner
 * and neighbours, Esc closes, neighbour click moves the selection,
 * search selects+opens the card, a failing state request keeps the old
 * colours and marks «данные устарели» after the configured time, a
 * geometry 404 MAP_VERSION_UNKNOWN triggers exactly one manifest
 * refetch, big-window visibility/label rules.
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { RouterProvider, createHashRouter } from '@vkontakte/vk-mini-apps-router';

// RouterProvider pings VK Bridge on navigation; outside VK it would hit
// a real fetch — stub it.
vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

import { PanelMap } from '../components/PanelMap';
import { MINI_MANIFEST } from '../fixtures/miniMap';
import type { MapManifestDTO } from '../types';
import {
  renderWithSession,
  stubMapFetch,
  versionUnknown,
  errorResponse,
} from './helpers';

function renderMap(stubOptions: Parameters<typeof stubMapFetch>[0] = {}) {
  const stub = stubMapFetch(stubOptions);
  window.location.hash = '#/map';
  const router = createHashRouter([
    { path: '/', panel: 'home', view: 'main' },
    { path: '/map', panel: 'map', view: 'main' },
  ]);
  const utils = renderWithSession(
    <RouterProvider router={router}>
      <PanelMap />
    </RouterProvider>,
  );
  return { ...utils, stub };
}

async function mapReady() {
  await waitFor(() =>
    expect(
      document.querySelectorAll('path[data-id]').length,
    ).toBeGreaterThan(0),
  );
}

function nodePath(id: number): SVGPathElement {
  const el = document.querySelector(`path[data-id="${id}"]`);
  expect(el).not.toBeNull();
  return el as SVGPathElement;
}

function clickNode(id: number) {
  fireEvent.mouseDown(nodePath(id), { button: 0, clientX: 5, clientY: 5 });
  fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));
}

describe('PanelMap — rendering', () => {
  it('renders one path per fixture node plus status, legend, attribution', async () => {
    renderMap();
    await mapReady();
    expect(document.querySelectorAll('path[data-id]')).toHaveLength(
      MINI_MANIFEST.nodes.length,
    );
    await screen.findByText(/Ход 7/, undefined, { timeout: 3000 });
    expect(screen.getByText('Свободная провинция')).toBeInTheDocument();
    expect(screen.getByText('Морская зона')).toBeInTheDocument();
    expect(
      screen.getByText('Mini fixture, no attribution'),
    ).toBeInTheDocument();
  });

  it('paints owned provinces in the owner colour and seas in sea colour', async () => {
    renderMap();
    await mapReady();
    await screen.findByText(/Ход 7/);
    expect(nodePath(1001).getAttribute('fill')).toBe('#e64545'); // Тестия
    expect(nodePath(1003).getAttribute('fill')).toBe(
      MINI_MANIFEST.rules.colors.neutral_province,
    );
    expect(nodePath(2001).getAttribute('fill')).toBe(
      MINI_MANIFEST.rules.colors.sea,
    );
  });
});

describe('PanelMap — node card', () => {
  it('click on a node opens the card with owner and neighbours', async () => {
    renderMap();
    await mapReady();
    await screen.findByText(/Ход 7/);

    clickNode(1001);
    const card = await screen.findByTestId('node-card');
    expect(within(card).getByText('Альфа')).toBeInTheDocument();
    expect(within(card).getByText('Провинция')).toBeInTheDocument();
    expect(within(card).getByText('Тестия')).toBeInTheDocument();
    // 1001 has one land edge to 1002.
    expect(within(card).getByText('Бета')).toBeInTheDocument();
    expect(within(card).getByText('сухопутная граница')).toBeInTheDocument();
    expect(card.querySelector('[data-slot="satellites"]')).not.toBeNull();
  });

  it('a sea zone card shows «Морская зона» and no owner row', async () => {
    renderMap();
    await mapReady();
    clickNode(2001);
    const card = await screen.findByTestId('node-card');
    expect(within(card).getByText('Северное мини-море')).toBeInTheDocument();
    expect(within(card).getByText('Морская зона')).toBeInTheDocument();
    expect(within(card).queryByText('Владелец')).not.toBeInTheDocument();
    // coast edge words shown (2001 touches 1004 and 1008)
    expect(
      within(card).getAllByText(/побережье/).length,
    ).toBeGreaterThan(0);
  });

  it('Esc closes the card', async () => {
    renderMap();
    await mapReady();
    clickNode(1001);
    await screen.findByTestId('node-card');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() =>
      expect(screen.queryByTestId('node-card')).not.toBeInTheDocument(),
    );
  });

  it('clicking a neighbour moves the selection to it', async () => {
    renderMap();
    await mapReady();
    clickNode(1005); // Эпсилон — strait to Дзета with 50 %
    const card = await screen.findByTestId('node-card');
    expect(within(card).getByText(/проходимость 50 %/)).toBeInTheDocument();

    await within(card).findByText('Дзета');
    fireEvent.click(within(card).getByText('Дзета'));
    const card2 = await screen.findByTestId('node-card');
    expect(within(card2).getByText('Дзета')).toBeInTheDocument();
    expect(document.querySelector('path[data-selected]')).toHaveAttribute(
      'data-selected',
      '1006',
    );
  });
});

describe('PanelMap — search (3.12)', () => {
  it('selecting a result selects the node and opens its card', async () => {
    renderMap();
    await mapReady();

    const field = screen.getByPlaceholderText(
      'Найти провинцию или морскую зону',
    );
    fireEvent.change(field, { target: { value: 'ель' } });
    const list = await screen.findByTestId('map-search-results');
    // 'ель' → Ель? fixture: 'Ёлкино' (ёл→ел) and 'Дельта'
    const options = within(list).getAllByRole('option');
    expect(options.length).toBeGreaterThan(0);

    fireEvent.click(within(list).getByText('Дельта'));
    const card = await screen.findByTestId('node-card');
    expect(within(card).getByText('Дельта')).toBeInTheDocument();
  });

  it('keyboard: arrows + Enter pick the highlighted result', async () => {
    renderMap();
    await mapReady();
    const field = screen.getByPlaceholderText(
      'Найти провинцию или морскую зону',
    );
    fireEvent.change(field, { target: { value: 'мин' } });
    await screen.findByTestId('map-search-results');
    fireEvent.keyDown(field, { key: 'Enter' }); // first result
    const card = await screen.findByTestId('node-card');
    expect(card).toBeInTheDocument();
  });
});

describe('PanelMap — refresh failures (3.10)', () => {
  it('keeps the old colours and marks «данные устарели» after stale_after', async () => {
    const fastRules: MapManifestDTO = {
      ...MINI_MANIFEST,
      rules: {
        ...MINI_MANIFEST.rules,
        refresh: {
          tick_refresh_delay_seconds: 5,
          tick_refresh_jitter_seconds: 30,
          retry_delay_seconds: 1,
          max_retries: 1,
          stale_after_seconds: 1,
        },
      },
    };
    let fail = false;
    renderMap({
      manifest: fastRules,
      onState: () => (fail ? errorResponse(500) : undefined),
    });
    await mapReady();
    await screen.findByText(/Ход 7/);
    expect(nodePath(1001).getAttribute('fill')).toBe('#e64545');

    fail = true;
    fireEvent(window, new Event('focus')); // "returning to the window"

    await screen.findByText(/данные устарели/, undefined, { timeout: 6000 });
    // Old colours stay — the last good state is never replaced.
    expect(nodePath(1001).getAttribute('fill')).toBe('#e64545');
  }, 10000);
});

describe('PanelMap — geometry version mismatch', () => {
  it('404 MAP_VERSION_UNKNOWN triggers exactly one manifest refetch', async () => {
    const { stub } = renderMap({
      onGeometry: (version) => versionUnknown(version),
    });
    await waitFor(() => expect(stub.calls.manifest).toBe(2), {
      timeout: 5000,
    });
    expect(stub.calls.geometry).toBe(2);
    await screen.findByText(/Не удалось загрузить геометрию/);
  });
});

describe('PanelMap — background layers', () => {
  it('confines inland_water to the view_box inside the transformed group', async () => {
    renderMap();
    await mapReady();
    const colors = MINI_MANIFEST.rules.colors;
    const view = document.querySelector(
      '[data-testid="map-view"]',
    ) as HTMLElement;
    const worldG = view.querySelector('svg > g') as SVGGElement;
    expect(worldG.querySelector('path[data-id]')).not.toBeNull();

    // The background rect lives in map coordinates = view_box, inside
    // the transformed group — visible only through the lakes of
    // `outside`.
    const water = view.querySelector(
      `rect[fill="${colors.inland_water}"]`,
    ) as SVGRectElement | null;
    expect(water).not.toBeNull();
    expect(worldG.contains(water)).toBe(true);
    const [x, y, w, h] = MINI_MANIFEST.view_box;
    expect(Number(water!.getAttribute('x'))).toBe(x);
    expect(Number(water!.getAttribute('y'))).toBe(y);
    expect(Number(water!.getAttribute('width'))).toBe(w);
    expect(Number(water!.getAttribute('height'))).toBe(h);
    // Layer order: the background sits under the outside path.
    expect(worldG.firstElementChild).toBe(water);

    // No element outside the world group may paint inland_water.
    const waterProbe = document.createElement('div');
    waterProbe.style.background = colors.inland_water;
    view.querySelectorAll('*').forEach((el) => {
      if (worldG.contains(el)) {
        return;
      }
      expect(el.getAttribute('fill')).not.toBe(colors.inland_water);
      expect((el as HTMLElement).style.background).not.toBe(
        waterProbe.style.background,
      );
    });
  });

  it('shows the outside colour beyond the view_box (pan margin / viewport overflow)', async () => {
    renderMap();
    await mapReady();
    const colors = MINI_MANIFEST.rules.colors;
    const view = document.querySelector(
      '[data-testid="map-view"]',
    ) as HTMLElement;

    // Best-effort drag to the clamp limit (jsdom has no layout — the
    // gesture is a no-op here, the assertion is the layer invariant).
    fireEvent.mouseDown(view, { button: 0, clientX: 50, clientY: 50 });
    fireEvent(
      window,
      new MouseEvent('mousemove', {
        bubbles: true,
        clientX: 5000,
        clientY: 5000,
      }),
    );
    fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));

    const probe = document.createElement('div');
    probe.style.background = colors.outside;
    expect(view.style.background).toBe(probe.style.background);
  });
});

describe('PanelMap — big window', () => {
  it('hides the button when fullscreen is unsupported', async () => {
    renderMap();
    await mapReady();
    // jsdom: fullscreenEnabled is falsy → hidden.
    expect(
      screen.queryByRole('button', { name: /Развернуть/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Назад' }),
    ).toBeInTheDocument();
  });

  it('hides the button when rules.big_window_enabled is false', async () => {
    const manifest: MapManifestDTO = {
      ...MINI_MANIFEST,
      rules: { ...MINI_MANIFEST.rules, big_window_enabled: false },
    };
    renderMap({ manifest });
    await mapReady();
    expect(
      screen.queryByRole('button', { name: /Развернуть/ }),
    ).not.toBeInTheDocument();
  });

  it('switches the label on fullscreenchange, driven by the event only', async () => {
    // jsdom has no fullscreen API — define the bits the browser provides.
    let fsElement: Element | null = null;
    const request = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(document, 'fullscreenEnabled', {
      configurable: true,
      get: () => true,
    });
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      get: () => fsElement,
    });
    Object.defineProperty(document.documentElement, 'requestFullscreen', {
      configurable: true,
      value: request,
    });
    try {
      renderMap();
      await mapReady();
      const button = await screen.findByRole('button', {
        name: 'Развернуть на весь экран',
      });
      fireEvent.click(button);
      expect(request).toHaveBeenCalled();

      // The browser flips into fullscreen: element set + event fired.
      fsElement = document.documentElement;
      fireEvent(document, new Event('fullscreenchange'));
      await screen.findByRole('button', { name: 'Свернуть' });
      // «Назад» is hidden in fullscreen.
      expect(
        screen.queryByRole('button', { name: 'Назад' }),
      ).not.toBeInTheDocument();
    } finally {
      delete (document as { fullscreenEnabled?: boolean }).fullscreenEnabled;
      delete (document as { fullscreenElement?: Element | null })
        .fullscreenElement;
      delete (
        document.documentElement as { requestFullscreen?: unknown }
      ).requestFullscreen;
    }
  });
});
