/**
 * ProvincePicker component tests (jsdom; network stubbed at the fetch
 * boundary with plain functions).
 *
 * Covered: counter «Выбрано N из M · минимум K», clicks toggle free
 * land provinces and update chips/counter/indicator, sea and occupied
 * clicks are refused with a hint, the maximum is enforced, «Готово»
 * gating (limits + connectivity), server disagreement keeps the picker
 * open with the server message, success returns ordered ids + display
 * names, cancel reports onCancel, chip removal updates the selection,
 * search only centres the view, Esc closes the search list first and
 * then the picker, and the session cache serves one geometry request
 * for the picker + the viewing screen.
 */

import { fireEvent, screen, waitFor } from '@testing-library/react';
import { ModalRoot } from '@vkontakte/vkui';

import { ProvincePicker } from '../components/ProvincePicker';
import { PanelMap } from '../components/PanelMap';
import { MINI_MANIFEST } from '../fixtures/miniMap';
import type { SelectionLimits } from '../lib/selection';
import { renderWithSession, stubMapFetch, errorResponse } from './helpers';
import { RouterProvider, createHashRouter } from '@vkontakte/vk-mini-apps-router';

vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    send: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    supports: vi.fn().mockReturnValue(false),
    isWebView: vi.fn().mockReturnValue(false),
  },
}));

const LIMITS: SelectionLimits = { min: 2, max: 3 };

interface RenderedPicker {
  onDone: ReturnType<typeof vi.fn>;
  onCancel: ReturnType<typeof vi.fn>;
  stub: ReturnType<typeof stubMapFetch>;
}

function renderPicker(
  stubOptions: Parameters<typeof stubMapFetch>[0] = {},
  props: Partial<
    Parameters<typeof ProvincePicker>[0]
  > = {},
): RenderedPicker {
  const stub = stubMapFetch(stubOptions);
  const onDone = vi.fn();
  const onCancel = vi.fn();
  renderWithSession(
    <ModalRoot activeModal="picker">
      <ProvincePicker
        id="picker"
        limits={LIMITS}
        onDone={onDone}
        onCancel={onCancel}
        {...props}
      />
    </ModalRoot>,
  );
  return { onDone, onCancel, stub };
}

/** Wait until the picker's map rendered its node paths. */
async function pickerReady() {
  await waitFor(() =>
    expect(
      document.querySelectorAll('[data-testid="map-view"] path[data-id]')
        .length,
    ).toBeGreaterThan(0),
  );
}

function nodePath(id: number): SVGPathElement {
  const el = document.querySelector(
    `[data-testid="map-view"] path[data-id="${id}"]`,
  );
  expect(el).not.toBeNull();
  return el as SVGPathElement;
}

/** A settled click on a node (mousedown on the path + window mouseup). */
function clickNode(id: number) {
  fireEvent.mouseDown(nodePath(id), { button: 0, clientX: 5, clientY: 5 });
  fireEvent(window, new MouseEvent('mouseup', { bubbles: true }));
}

const doneButton = () =>
  screen.getByRole('button', { name: 'Готово' }) as HTMLButtonElement;
const counter = () => screen.getByTestId('picker-count').textContent;

describe('ProvincePicker', () => {
  it('shows the counter with min/max and Готово disabled while empty', async () => {
    renderPicker();
    await pickerReady();
    expect(counter()).toBe('Выбрано 0 из 3 · минимум 2');
    expect(doneButton()).toBeDisabled();
  });

  it('keeps an initial selection and reports it in the counter', async () => {
    renderPicker({}, { initialSelectedIds: [1003, 1004] });
    await pickerReady();
    expect(counter()).toBe('Выбрано 2 из 3 · минимум 2');
    // Selected provinces appear as named chips.
    expect(screen.getByText('Гамма')).toBeInTheDocument();
    expect(screen.getByText('Дельта')).toBeInTheDocument();
    expect(screen.getByText('Территория связна')).toBeInTheDocument();
    expect(doneButton()).toBeEnabled();
  });

  it('clicking free land provinces updates chips, counter, indicator', async () => {
    renderPicker();
    await pickerReady();

    clickNode(1005); // Эпсилон
    expect(counter()).toBe('Выбрано 1 из 3 · минимум 2');
    expect(screen.getByText('Эпсилон')).toBeInTheDocument();
    expect(screen.getByText('Территория связна')).toBeInTheDocument();
    // Below the minimum → Готово stays disabled.
    expect(doneButton()).toBeDisabled();

    clickNode(1006); // Дзета — strait-connected to Эпсилон
    expect(counter()).toBe('Выбрано 2 из 3 · минимум 2');
    expect(screen.getByText('Дзета')).toBeInTheDocument();
    expect(screen.getByText('Территория связна')).toBeInTheDocument();
    expect(doneButton()).toBeEnabled();

    clickNode(1007); // Эта — strait chain continues
    expect(counter()).toBe('Выбрано 3 из 3 · минимум 2');
    expect(doneButton()).toBeEnabled();
  });

  it('clicking a selected province again toggles it off', async () => {
    renderPicker();
    await pickerReady();
    clickNode(1003);
    clickNode(1004);
    clickNode(1003); // off
    expect(counter()).toBe('Выбрано 1 из 3 · минимум 2');
    expect(screen.queryByText('Гамма')).not.toBeInTheDocument();
  });

  it('refuses a sea node with a hint', async () => {
    renderPicker();
    await pickerReady();
    clickNode(2001);
    expect(counter()).toBe('Выбрано 0 из 3 · минимум 2');
    expect(screen.getByTestId('picker-hint')).toHaveTextContent(
      'Морскую зону выбрать нельзя',
    );
  });

  it('refuses an occupied node with a hint', async () => {
    renderPicker();
    await pickerReady();
    clickNode(1001); // owned by «Тестия» in MINI_STATE
    expect(counter()).toBe('Выбрано 0 из 3 · минимум 2');
    expect(screen.getByTestId('picker-hint')).toHaveTextContent(
      'Эта провинция уже занята',
    );
  });

  it('refuses a click beyond the maximum', async () => {
    renderPicker({}, { limits: { min: 1, max: 1 } });
    await pickerReady();
    clickNode(1003);
    clickNode(1004);
    expect(counter()).toBe('Выбрано 1 из 1 · минимум 1');
    expect(screen.getByTestId('picker-hint')).toHaveTextContent(
      'Выбрано максимум — 1 провинция',
    );
  });

  it('shows «Не связна: 2 части» and disables Готово when the rule is on', async () => {
    renderPicker();
    await pickerReady();
    clickNode(1003);
    clickNode(1005); // far away — no land/strait path to 1003
    expect(screen.getByTestId('picker-connectivity')).toHaveTextContent(
      'Не связна: 2 части',
    );
    expect(doneButton()).toBeDisabled();
  });

  it('require_connected_start=false makes the indicator informational', async () => {
    const manifest = {
      ...MINI_MANIFEST,
      rules: { ...MINI_MANIFEST.rules, require_connected_start: false },
    };
    renderPicker({ manifest });
    await pickerReady();
    clickNode(1003);
    clickNode(1005);
    expect(screen.getByTestId('picker-connectivity')).toHaveTextContent(
      'Не связна: 2 части',
    );
    expect(doneButton()).toBeEnabled();
  });

  it('Готово asks the server and returns ordered ids + names', async () => {
    const { onDone, stub } = renderPicker();
    await pickerReady();
    clickNode(1005);
    clickNode(1006);
    await waitFor(() => expect(doneButton()).toBeEnabled());
    fireEvent.click(doneButton());
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(stub.checkRequests).toEqual([[1005, 1006]]);
    const [ids, names] = onDone.mock.calls[0] as [
      number[],
      Map<number, string>,
    ];
    expect(ids).toEqual([1005, 1006]);
    expect(names.get(1005)).toBe('Эпсилон');
    expect(names.get(1006)).toBe('Дзета');
  });

  it('server disagreement keeps the picker open with the server message', async () => {
    const { onDone } = renderPicker({
      onCheck: () =>
        new Response(
          JSON.stringify({ connected: false, component_count: 2 }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
    });
    await pickerReady();
    clickNode(1005);
    clickNode(1006); // locally connected — the server disagrees
    await waitFor(() => expect(doneButton()).toBeEnabled());
    fireEvent.click(doneButton());
    await screen.findByText('Не связна: 2 части', {
      selector: '[data-testid="picker-server-message"] *',
    });
    expect(onDone).not.toHaveBeenCalled();
    expect(doneButton()).toBeInTheDocument(); // still open
  });

  it('a check error keeps the picker open and shows the message', async () => {
    const { onDone } = renderPicker({
      onCheck: () => errorResponse(500, 'CHECK_BROKEN'),
    });
    await pickerReady();
    clickNode(1003);
    clickNode(1004);
    await waitFor(() => expect(doneButton()).toBeEnabled());
    fireEvent.click(doneButton());
    await screen.findByTestId('picker-server-message');
    expect(onDone).not.toHaveBeenCalled();
  });

  it('Отмена reports onCancel without touching the selection', async () => {
    const { onDone, onCancel } = renderPicker();
    await pickerReady();
    clickNode(1003);
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onDone).not.toHaveBeenCalled();
  });

  it('removing a chip updates the selection', async () => {
    renderPicker();
    await pickerReady();
    clickNode(1005);
    clickNode(1006);
    fireEvent.click(
      screen.getByRole('button', { name: /Удалить Эпсилон/ }),
    );
    expect(counter()).toBe('Выбрано 1 из 3 · минимум 2');
    expect(screen.queryByText('Эпсилон')).not.toBeInTheDocument();
  });

  it('search only centres the view — it never toggles the selection', async () => {
    renderPicker();
    await pickerReady();
    const search = screen.getByPlaceholderText('Найти провинцию');
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: 'эпс' } });
    const result = await screen.findByText('Эпсилон', {
      selector: '[data-result-id]',
    });
    fireEvent.click(result);
    expect(counter()).toBe('Выбрано 0 из 3 · минимум 2');
    expect(screen.queryByText('Эпсилон', { selector: 'span' })).toBeNull();
  });

  it('Esc closes the search list first, then the picker', async () => {
    const { onCancel } = renderPicker();
    await pickerReady();
    const search = screen.getByPlaceholderText('Найти провинцию');
    fireEvent.focus(search);
    fireEvent.change(search, { target: { value: 'эпс' } });
    await screen.findByTestId('picker-search-results');

    // First Esc: the list closes, the modal stays.
    fireEvent.keyDown(search, { key: 'Escape' });
    expect(
      screen.queryByTestId('picker-search-results'),
    ).not.toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();

    // Second Esc — with focus on modal content (VKUI's Search swallows
    // Esc while focused; the modal's close path sees events inside it).
    fireEvent.keyDown(screen.getByTestId('province-picker'), {
      key: 'Escape',
    });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('picker + viewing screen share one geometry download per session', async () => {
    window.location.hash = '#/map';
    const stub = stubMapFetch();
    const router = createHashRouter([
      { path: '/', panel: 'home', view: 'main' },
      { path: '/map', panel: 'map', view: 'main' },
    ]);
    renderWithSession(
      <RouterProvider router={router}>
        <>
          <PanelMap />
          <ModalRoot activeModal="picker">
            <ProvincePicker
              id="picker"
              limits={LIMITS}
              onDone={vi.fn()}
              onCancel={vi.fn()}
            />
          </ModalRoot>
        </>
      </RouterProvider>,
    );
    await pickerReady();
    expect(stub.calls.geometry).toBe(1);
    // The manifest is revalidated once per mount (If-None-Match 304),
    // but the body is downloaded only once.
    expect(stub.calls.geometry).toBe(1);
  });
});
