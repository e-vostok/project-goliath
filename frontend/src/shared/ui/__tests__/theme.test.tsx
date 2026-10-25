/**
 * Theme resolution (UI Spec 5.4): a stored mode wins over «авто», «авто»
 * follows the scheme VK reports (VKWebAppUpdateConfig), an unknown
 * scheme gives dark. The bridge is stubbed so tests can speak «VK».
 */

import { act, render, screen, waitFor } from '@testing-library/react';

import { ThemeProvider, useTheme } from '../theme';

const bridgeMock = vi.hoisted(() => {
  const listeners = new Set<(event: unknown) => void>();
  return {
    listeners,
    send: vi.fn(() => new Promise(() => {})),
  };
});

vi.mock('@vkontakte/vk-bridge', () => ({
  default: {
    subscribe: (listener: (event: unknown) => void) => {
      bridgeMock.listeners.add(listener);
    },
    unsubscribe: (listener: (event: unknown) => void) => {
      bridgeMock.listeners.delete(listener);
    },
    send: bridgeMock.send,
  },
}));

function emitVkScheme(scheme: string) {
  act(() => {
    for (const listener of bridgeMock.listeners) {
      listener({
        detail: { type: 'VKWebAppUpdateConfig', data: { scheme } },
      });
    }
  });
}

function Probe() {
  const { mode, resolved, vkScheme } = useTheme();
  return (
    <div data-testid="probe">
      {mode}:{resolved}:{vkScheme ?? 'none'}
    </div>
  );
}

async function renderProbe() {
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  // The provider subscribes to vk-bridge through a dynamic import —
  // wait until the listener is registered before tests emit schemes.
  await waitFor(() =>
    expect(bridgeMock.listeners.size).toBeGreaterThan(0),
  );
  return screen.getByTestId('probe');
}

afterEach(() => {
  window.localStorage.clear();
  bridgeMock.listeners.clear();
});

describe('theme resolution', () => {
  it('lets a stored mode win over the VK scheme', async () => {
    window.localStorage.setItem('pax.theme', 'light');
    const probe = await renderProbe();
    expect(probe).toHaveTextContent('light:light');
    emitVkScheme('vkcom_dark');
    expect(probe).toHaveTextContent('light:light:vkcom_dark');
  });

  it.each([
    ['vkcom_dark', 'dark'],
    ['space_gray', 'dark'],
    ['bright_light', 'light'],
  ])(
    'in «авто» follows the reported scheme %s → %s',
    async (scheme, resolved) => {
      const probe = await renderProbe();
      emitVkScheme(scheme);
      expect(probe).toHaveTextContent(`auto:${resolved}:${scheme}`);
    },
  );

  it('resolves an unknown scheme to dark', async () => {
    const probe = await renderProbe();
    emitVkScheme('some_future_scheme');
    expect(probe).toHaveTextContent('auto:dark:some_future_scheme');
  });
});
