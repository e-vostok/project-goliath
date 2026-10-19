/**
 * Regression test (track B): the `#ui-kit` catalogue entry must send
 * `VKWebAppInit` through vk-bridge — without the handshake VK shows its
 * loading spinner forever. Only the bridge module is mocked, like the
 * theme test.
 */

import { render } from '@testing-library/react';

import { UiKitEntry } from '../UiKitEntry';

const bridgeMock = vi.hoisted(() => ({
  send: vi.fn((..._args: unknown[]) => new Promise(() => {})),
  subscribe: vi.fn(),
  unsubscribe: vi.fn(),
}));

vi.mock('@vkontakte/vk-bridge', () => ({ default: bridgeMock }));

describe('UiKitEntry', () => {
  it('sends VKWebAppInit exactly once, before VKWebAppGetConfig', () => {
    render(<UiKitEntry />);

    const calls = bridgeMock.send.mock.calls.map(([method]) => method);
    expect(calls.filter((m) => m === 'VKWebAppInit')).toHaveLength(1);
    if (calls.includes('VKWebAppGetConfig')) {
      expect(calls.indexOf('VKWebAppInit')).toBeLessThan(
        calls.indexOf('VKWebAppGetConfig'),
      );
    }
  });
});
