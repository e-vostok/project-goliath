/**
 * Probe runners A–F: stub objects are passed in for bridge/window/targets
 * (nothing mocks the logic under test). Each runner must return a
 * ProbeBlock, and a throwing/rejecting underlying call must surface as
 * `ok:false` + `error {name, message}` — never as an unhandled rejection.
 */

import {
  runEnvironmentProbe,
  runFullscreenProbe,
  runOpenTabProbe,
  runOpenVkAppProbe,
  runResizeProbe,
  type BridgeLike,
  type FullscreenTarget,
} from '../probes';
import { E1_PROBE_CHILD_HASH } from '../types';

const stubBridge = (overrides: Partial<BridgeLike> = {}): BridgeLike => ({
  supports: () => true,
  send: async () => ({}),
  ...overrides,
});

const SECRET_LAUNCH_PARAMS = {
  vk_app_id: 777,
  vk_platform: 'desktop_web',
  vk_client: 'browser',
  vk_ref: 'menu',
  vk_user_id: 424242,
  sign: 'SECRET_SIGN_VALUE',
  access_token: 'SECRET_TOKEN',
};

describe('probe A — Среда', () => {
  it('whitelists launch params and config — no secrets can leak', async () => {
    const bridge = stubBridge({
      send: async (method: string) =>
        method === 'VKWebAppGetLaunchParams'
          ? { ...SECRET_LAUNCH_PARAMS }
          : {
              app: 'vk-app',
              appearance: 'light',
              scheme: 'vkcom_light',
              viewport_width: 1000,
              viewport_height: 1200,
              secret_config_key: 'SECRET_CONFIG',
            },
    });

    const block = await runEnvironmentProbe(bridge, window, document);

    expect(block.probe).toBe('A');
    expect(block.ok).toBe(true);
    const result = block.result as {
      bridge: {
        supportsResizeWindow: boolean;
        launchParams: Record<string, unknown>;
        config: Record<string, unknown>;
      };
    };
    expect(result.bridge.supportsResizeWindow).toBe(true);
    expect(result.bridge.launchParams).toEqual({
      vk_platform: 'desktop_web',
      vk_client: 'browser',
      vk_app_id: 777,
      vk_ref: 'menu',
    });

    const asText = JSON.stringify(block);
    for (const leaked of [
      'SECRET_SIGN_VALUE',
      'SECRET_TOKEN',
      'SECRET_CONFIG',
      'vk_user_id',
      '424242',
    ]) {
      expect(asText).not.toContain(leaked);
    }
  });

  it('records VK call failures per-call instead of failing the probe', async () => {
    const bridge = stubBridge({
      send: async () => {
        throw new Error('bridge offline');
      },
    });

    const block = await runEnvironmentProbe(bridge, window, document);

    expect(block.ok).toBe(true);
    const asText = JSON.stringify(block.result);
    expect(asText).toContain('bridge offline');
  });
});

describe('probes B/C — fullscreen', () => {
  it('records resolved outcome, the event and metrics', async () => {
    const target: FullscreenTarget = {
      requestFullscreen: () => {
        document.dispatchEvent(new Event('fullscreenchange'));
        return Promise.resolve();
      },
    };

    const block = await runFullscreenProbe(
      'B',
      'Полный экран: этот блок',
      target,
      window,
      document,
      0,
    );

    expect(block.ok).toBe(true);
    const result = block.result as {
      call: string;
      events: string[];
      metricsAfter: { innerWidth: number | null };
    };
    expect(result.call).toBe('resolved');
    expect(result.events).toContain('fullscreenchange');
    expect(result.metricsAfter.innerWidth).toBe(window.innerWidth);
  });

  it('rejection becomes ok:false with error name/message', async () => {
    const target: FullscreenTarget = {
      requestFullscreen: () =>
        Promise.reject(
          Object.assign(new Error('denied'), { name: 'NotAllowedError' }),
        ),
    };

    const block = await runFullscreenProbe(
      'C',
      'Полный экран: вся страница',
      target,
      window,
      document,
      0,
    );

    expect(block.ok).toBe(false);
    expect(block.error).toEqual({
      name: 'NotAllowedError',
      message: 'denied',
    });
    // …but the metrics snapshot was still taken.
    const result = block.result as { call: { rejected: { name: string } } };
    expect(result.call.rejected.name).toBe('NotAllowedError');
  });

  it('a synchronous throw also becomes ok:false', async () => {
    const target: FullscreenTarget = {
      requestFullscreen: () => {
        throw new Error('sync boom');
      },
    };
    const block = await runFullscreenProbe(
      'B',
      'x',
      target,
      window,
      document,
      0,
    );
    expect(block.ok).toBe(false);
    expect(block.error?.name).toBe('Error');
    expect(block.error?.message).toBe('sync boom');
  });

  it('falls back to webkitRequestFullscreen, else reports unavailable', async () => {
    const webkit = vi.fn(() => Promise.resolve());
    const webkitOnly: FullscreenTarget = { webkitRequestFullscreen: webkit };
    const block1 = await runFullscreenProbe(
      'B',
      'x',
      webkitOnly,
      window,
      document,
      0,
    );
    expect(webkit).toHaveBeenCalledTimes(1);
    expect(block1.ok).toBe(true);

    const block2 = await runFullscreenProbe(
      'B',
      'x',
      {},
      window,
      document,
      0,
    );
    expect(block2.ok).toBe(true);
    expect((block2.result as { call: string }).call).toBe('unavailable');
  });
});

describe('probe D — VKWebAppResizeWindow', () => {
  it('records the resolved value and post-metrics', async () => {
    const send = vi.fn(async () => ({ width: 1400, height: 1200 }));
    const block = await runResizeProbe(
      1400,
      1200,
      stubBridge({ send }),
      window,
      document,
      0,
    );

    expect(send).toHaveBeenCalledWith('VKWebAppResizeWindow', {
      width: 1400,
      height: 1200,
    });
    expect(block.ok).toBe(true);
    const result = block.result as {
      request: { width: number; height: number };
      resolved: unknown;
      metricsAfter: unknown;
    };
    expect(result.request).toEqual({ width: 1400, height: 1200 });
    expect(result.resolved).toEqual({ width: 1400, height: 1200 });
    expect(result.metricsAfter).toBeTruthy();
  });

  it('a VK rejection yields ok:false with error_type/error_data preserved', async () => {
    const vkError = {
      error_type: 'client_error',
      error_data: { error_code: 4, error_reason: 'Too wide' },
    };
    const block = await runResizeProbe(
      1400,
      1200,
      stubBridge({ send: async () => Promise.reject(vkError) }),
      window,
      document,
      0,
    );

    expect(block.ok).toBe(false);
    expect(block.error?.name).toBe('client_error');
    expect(block.error?.error_type).toBe('client_error');
    expect(block.error?.error_data).toEqual(vkError.error_data);
  });
});

describe('probe E — open own address', () => {
  it('records both attempts; noopener returning null is by design', () => {
    const open = vi
      .fn()
      .mockReturnValueOnce(null)
      .mockReturnValueOnce({} as Window);
    const fakeWin = {
      location: { origin: 'https://app.example', pathname: '/' },
      open,
    } as unknown as Window;

    const block = runOpenTabProbe(fakeWin);

    expect(block.ok).toBe(true);
    expect(open).toHaveBeenNthCalledWith(
      1,
      `https://app.example/${E1_PROBE_CHILD_HASH}`,
      '_blank',
      'noopener',
    );
    expect(open).toHaveBeenNthCalledWith(
      2,
      `https://app.example/${E1_PROBE_CHILD_HASH}`,
      '_blank',
    );
    const result = block.result as {
      withNoopener: { returned: string };
      withoutNoopener: { returned: string };
    };
    expect(result.withNoopener.returned).toBe('null');
    expect(result.withoutNoopener.returned).toBe('window');
  });
});

describe('probe F — open vk.com/app<id>', () => {
  it('opens the app page using vk_app_id from launch params', async () => {
    const open = vi.fn().mockReturnValue({} as Window);
    const fakeWin = { open } as unknown as Window;
    const block = await runOpenVkAppProbe(
      stubBridge({ send: async () => ({ ...SECRET_LAUNCH_PARAMS }) }),
      fakeWin,
    );

    expect(block.ok).toBe(true);
    expect(open).toHaveBeenCalledWith('https://vk.com/app777', '_blank');
    const asText = JSON.stringify(block);
    expect(asText).not.toContain('SECRET_SIGN_VALUE');
    expect(asText).not.toContain('SECRET_TOKEN');
  });

  it('fails cleanly when vk_app_id is absent', async () => {
    const block = await runOpenVkAppProbe(
      stubBridge({ send: async () => ({ vk_platform: 'desktop_web' }) }),
      { open: vi.fn() } as unknown as Window,
    );
    expect(block.ok).toBe(false);
    expect(block.error?.name).toBe('MISSING_APP_ID');
  });

  it('a bridge rejection becomes ok:false with error name/message', async () => {
    const block = await runOpenVkAppProbe(
      stubBridge({
        send: async () => Promise.reject(new Error('bridge dead')),
      }),
      { open: vi.fn() } as unknown as Window,
    );
    expect(block.ok).toBe(false);
    expect(block.error?.message).toBe('bridge dead');
  });
});
