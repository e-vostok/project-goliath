/**
 * The child-tab entry branch: '#e1-probe-child' must produce the standalone
 * child page element — anything else returns null so main.tsx renders the
 * normal app. The child page renders with no providers and no VK Bridge.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { isValidElement } from 'react';

import {
  E1_PROBE_CHILD_HASH,
  e1ChildEntry,
  isE1ProbeChildHash,
} from '../childEntry';
import { E1ProbeChildPage } from '../E1ProbeChildPage';

describe('e1ChildEntry', () => {
  it('returns the child page element for the probe hash', () => {
    const element = e1ChildEntry(E1_PROBE_CHILD_HASH);
    expect(isValidElement(element)).toBe(true);
    expect(element?.type).toBe(E1ProbeChildPage);
  });

  it('returns null for any other hash → normal app renders', () => {
    expect(e1ChildEntry('')).toBeNull();
    expect(e1ChildEntry('#other')).toBeNull();
    expect(e1ChildEntry('#e1-probe-child-extra')).toBeNull();
  });

  it('isE1ProbeChildHash flags only the exact hash', () => {
    expect(isE1ProbeChildHash('#e1-probe-child')).toBe(true);
    expect(isE1ProbeChildHash('e1-probe-child')).toBe(false);
    expect(isE1ProbeChildHash('')).toBe(false);
  });
});

describe('E1ProbeChildPage', () => {
  it('renders standalone — no providers, no VK Bridge, no API', () => {
    render(<E1ProbeChildPage />);

    expect(
      screen.getByRole('heading', { name: /дочерняя вкладка/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', {
        name: 'Полный экран: вся страница',
      }),
    ).toBeInTheDocument();

    const log = screen.getByTestId(
      'e1-child-report',
    ) as HTMLTextAreaElement;
    expect(log.value).toContain('E1-1');
    expect(log.value).toContain('"probe": "CHILD"');
    expect(log.value).toContain('"metrics"');
  });

  it('fullscreen button appends its outcome block', async () => {
    render(<E1ProbeChildPage />);
    screen
      .getByRole('button', { name: 'Полный экран: вся страница' })
      .click();

    const log = screen.getByTestId('e1-child-report') as HTMLTextAreaElement;
    // jsdom has no requestFullscreen → the API-absence outcome is recorded
    // once the probe (600 ms metrics delay) resolves.
    await waitFor(() => expect(log.value).toContain('"probe": "C"'), {
      timeout: 3000,
    });
    expect(log.value).toContain('"unavailable"');
  });
});
