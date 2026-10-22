/**
 * Notice — the shared «done» bar (UI Spec 7, version 0.9.0 unit 9):
 * shows the text inside the app root container the host portals into,
 * a new message replaces the old one (one bar at a time), disappears
 * after 4 s and closes on click.
 */

import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useRef } from 'react';

import { NoticeHost, NOTICE_TIMEOUT_MS, useNotice } from '../Notice';

function Buttons() {
  const notify = useNotice();
  return (
    <>
      <button onClick={() => notify('Первое')}>send-first</button>
      <button onClick={() => notify('Второе')}>send-second</button>
    </>
  );
}

/** Mirrors the AppShell wiring: a relative root container + the host. */
function Harness() {
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} data-testid="host-root">
      <NoticeHost container={containerRef}>
        <Buttons />
      </NoticeHost>
    </div>
  );
}

const hostRoot = () => screen.getByTestId('host-root');

afterEach(() => {
  vi.useRealTimers();
});

describe('Notice — the shared «done» bar', () => {
  it('shows the text inside the app root container', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'send-first' }));

    const notice = screen.getByTestId('notice');
    expect(within(notice).getByText('Первое')).toBeInTheDocument();
    // The bar lives IN the root container, not at the page level.
    expect(hostRoot().contains(notice)).toBe(true);
  });

  it('a new message replaces the previous one — one bar at a time', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'send-first' }));
    fireEvent.click(screen.getByRole('button', { name: 'send-second' }));

    expect(screen.getAllByTestId('notice')).toHaveLength(1);
    expect(screen.getByTestId('notice')).toHaveTextContent('Второе');
    expect(screen.queryByText('Первое')).not.toBeInTheDocument();
  });

  it('disappears after 4 s and closes on click', () => {
    vi.useFakeTimers();
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: 'send-first' }));
    expect(screen.getByTestId('notice')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(NOTICE_TIMEOUT_MS - 1);
    });
    expect(screen.getByTestId('notice')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByTestId('notice')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'send-second' }));
    fireEvent.click(screen.getByTestId('notice'));
    expect(screen.queryByTestId('notice')).not.toBeInTheDocument();
  });
});
