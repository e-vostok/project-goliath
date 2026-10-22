/**
 * Popup + PopupHost — the shared «Всплывающее окно» (UI Spec 3.3).
 *
 * Covers: Esc and the scrim close only the TOP popup; `dirty` blocks
 * both while the «×» still closes; an S over an M is legal while an M
 * over an M and a third level throw; focus moves into the window on
 * open and returns on close; the host container gets `min-height`
 * while a popup is open and loses it when the last one closes.
 */

import { useRef, useState, type ReactNode } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { Popup, PopupHost } from '../Popup';
import type { PopupSize } from '../Popup';

/** ResizeObserver that lets the test fire a measure on demand. */
class MockResizeObserver {
  static instances: MockResizeObserver[] = [];
  private cb: ResizeObserverCallback;
  private el: Element | null = null;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
    MockResizeObserver.instances.push(this);
  }
  observe(el: Element) {
    this.el = el;
  }
  unobserve() {}
  disconnect() {}
  trigger() {
    this.cb(
      [{ target: this.el } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
}

type Win = {
  size: PopupSize;
  title: string;
  dirty?: boolean;
  flush?: boolean;
};

function Harness({
  wins,
  extra,
}: {
  wins: Win[];
  extra?: ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} data-testid="host-root">
      <PopupHost container={containerRef}>
        {extra}
        {wins.map((w) => (
          <Popup
            key={w.title}
            size={w.size}
            title={w.title}
            icon="document"
            dirty={w.dirty}
            flush={w.flush}
            onClose={() => {}}
            testId={`popup-${w.title}`}
          >
            <input aria-label={`Поле ${w.title}`} />
          </Popup>
        ))}
      </PopupHost>
    </div>
  );
}

/** A stateful bench: buttons open real windows, close calls drop them. */
function StatefulBench() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState(false);
  const [confirm, setConfirm] = useState(false);
  return (
    <div ref={containerRef} data-testid="host-root">
      <PopupHost container={containerRef}>
        <button onClick={() => setForm(true)}>Открыть форму</button>
        {form && (
          <Popup
            size="M"
            title="Форма"
            onClose={() => {
              setForm(false);
              setConfirm(false);
            }}
            testId="popup-form"
            footer={
              <button onClick={() => setConfirm(true)}>
                Отправить приказ
              </button>
            }
          >
            <input aria-label="Поле формы" />
          </Popup>
        )}
        {confirm && (
          <Popup
            size="S"
            title="Подтверждение"
            onClose={() => setConfirm(false)}
            testId="popup-confirm"
            footer={<button onClick={() => setConfirm(false)}>Да</button>}
          >
            Точно?
          </Popup>
        )}
      </PopupHost>
    </div>
  );
}

beforeEach(() => {
  MockResizeObserver.instances = [];
  vi.stubGlobal('ResizeObserver', MockResizeObserver);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Popup — Esc and scrim', () => {
  it('Esc closes only the top popup; a second Esc closes the one below', async () => {
    const user = userEvent.setup();
    render(<StatefulBench />);
    await user.click(
      screen.getByRole('button', { name: 'Открыть форму' }),
    );
    await screen.findByTestId('popup-form');
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    await screen.findByTestId('popup-confirm');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('popup-confirm')).not.toBeInTheDocument();
    expect(screen.getByTestId('popup-form')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('popup-form')).not.toBeInTheDocument();
  });

  it('a scrim click closes only the top popup', async () => {
    const user = userEvent.setup();
    render(<StatefulBench />);
    await user.click(
      screen.getByRole('button', { name: 'Открыть форму' }),
    );
    await user.click(
      screen.getByRole('button', { name: 'Отправить приказ' }),
    );
    await screen.findByTestId('popup-confirm');

    fireEvent.click(screen.getByTestId('popup-confirm-scrim'));
    expect(screen.queryByTestId('popup-confirm')).not.toBeInTheDocument();
    expect(screen.getByTestId('popup-form')).toBeInTheDocument();
  });

  it('dirty blocks Esc and the scrim, but the «×» still closes', async () => {
    const containerRef = { current: null as HTMLDivElement | null };
    function DirtyWin() {
      const [open, setOpen] = useState(true);
      return (
        <div
          ref={(el) => {
            containerRef.current = el;
          }}
        >
          <PopupHost container={containerRef}>
            {open && (
              <Popup
                size="M"
                title="Грязная форма"
                dirty
                onClose={() => setOpen(false)}
                testId="popup-dirty"
              >
                <input aria-label="Поле" />
              </Popup>
            )}
          </PopupHost>
        </div>
      );
    }
    const user = userEvent.setup();
    render(<DirtyWin />);
    const popup = await screen.findByTestId('popup-dirty');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(popup).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('popup-dirty-scrim'));
    expect(popup).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Закрыть' }));
    expect(screen.queryByTestId('popup-dirty')).not.toBeInTheDocument();
  });

  it('an Esc a window part already consumed (defaultPrevented) does not close', async () => {
    const onClose = vi.fn();
    const containerRef = { current: null as HTMLDivElement | null };
    render(
      <div
        ref={(el) => {
          containerRef.current = el;
        }}
      >
        <PopupHost container={containerRef}>
          <Popup
            size="M"
            title="Форма"
            onClose={onClose}
            testId="popup-eaten-esc"
          >
            <input
              aria-label="Поле"
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.preventDefault();
                }
              }}
            />
          </Popup>
        </PopupHost>
      </div>,
    );
    await screen.findByTestId('popup-eaten-esc');

    // The field handled Esc itself → the popup ignores the event.
    fireEvent.keyDown(screen.getByLabelText('Поле'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();

    // An unconsumed Esc still reaches onClose.
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('Popup — nesting rules', () => {
  it('allows an S over an M', () => {
    render(
      <Harness
        wins={[
          { size: 'M', title: 'Форма' },
          { size: 'S', title: 'Подтверждение' },
        ]}
      />,
    );
    expect(screen.getByTestId('popup-Форма')).toBeInTheDocument();
    expect(
      screen.getByTestId('popup-Подтверждение'),
    ).toBeInTheDocument();
  });

  it('throws when an M tries to open over another popup', () => {
    expect(() =>
      render(
        <Harness
          wins={[
            { size: 'M', title: 'Форма' },
            { size: 'M', title: 'Вторая форма' },
          ]}
        />,
      ),
    ).toThrow(/only an 'S' popup may lie over another popup/);
  });

  it('throws on a third level even for an S', () => {
    expect(() =>
      render(
        <Harness
          wins={[
            { size: 'M', title: 'Форма' },
            { size: 'S', title: 'Подтверждение' },
            { size: 'S', title: 'Третье' },
          ]}
        />,
      ),
    ).toThrow(/nesting beyond one level is forbidden/);
  });
});

describe('Popup — focus', () => {
  it('focuses the first field on open and returns focus on close', async () => {
    const user = userEvent.setup();
    render(<StatefulBench />);
    const opener = screen.getByRole('button', { name: 'Открыть форму' });
    await user.click(opener);

    await screen.findByTestId('popup-form');
    expect(screen.getByLabelText('Поле формы')).toHaveFocus();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('popup-form')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});

describe('Popup — flush body', () => {
  it('flush removes the body padding and gap; a normal body keeps them', () => {
    render(
      <Harness
        wins={[
          { size: 'M', title: 'Обычное' },
          { size: 'S', title: 'Плоское', flush: true },
        ]}
      />,
    );
    const normal = screen
      .getByTestId('popup-Обычное')
      .querySelector('[data-popup-body]') as HTMLElement;
    const flushed = screen
      .getByTestId('popup-Плоское')
      .querySelector('[data-popup-body]') as HTMLElement;
    expect(Number.parseFloat(normal.style.padding)).toBeGreaterThan(0);
    expect(Number.parseFloat(normal.style.gap)).toBeGreaterThan(0);
    expect(Number.parseFloat(flushed.style.padding)).toBe(0);
    expect(Number.parseFloat(flushed.style.gap)).toBe(0);
  });
});

describe('Popup — container min-height', () => {
  it('grows the root container while open and frees it on close', async () => {
    const user = userEvent.setup();
    render(<StatefulBench />);
    const root = screen.getByTestId('host-root');
    expect(root.style.minHeight).toBe('');

    await user.click(
      screen.getByRole('button', { name: 'Открыть форму' }),
    );
    const popup = await screen.findByTestId('popup-form');
    // A real measure: 200 px window → 64 top + 200 + 24 bottom gap.
    vi.spyOn(popup, 'offsetHeight', 'get').mockReturnValue(200);
    MockResizeObserver.instances.forEach((ro) => ro.trigger());
    expect(root.style.minHeight).toBe('288px');

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('popup-form')).not.toBeInTheDocument();
    expect(root.style.minHeight).toBe('');
  });
});
