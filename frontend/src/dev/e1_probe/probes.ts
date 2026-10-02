/**
 * Probe runners A–F for the E1 «big window» panel.
 *
 * Every runner returns a ProbeBlock: `ok:true` with `result` on success,
 * `ok:false` with `error {name, message}` (plus VK `error_type`/`error_data`
 * when present) when the probed call throws or rejects. All browser/bridge
 * dependencies arrive as arguments — nothing here touches globals directly,
 * so tests can pass plain stub objects.
 */

import {
  collectMetrics,
  delay,
  pickWhitelisted,
  redactUrl,
  toErrorInfo,
  type ErrorInfo,
} from './helpers';
import { E1_PROBE_CHILD_HASH, type ProbeBlock } from './types';

/** Minimal shape of @vkontakte/vk-bridge used by the probes. */
export interface BridgeLike {
  supports(method: string): boolean;
  send(method: string, params?: Record<string, unknown>): Promise<unknown>;
}

/** Launch-params keys the report is allowed to show — never values like
 *  `sign`, tokens or user ids. */
export const LAUNCH_PARAM_KEYS = [
  'vk_platform',
  'vk_client',
  'vk_app_id',
  'vk_ref',
] as const;

export const CONFIG_KEYS = [
  'app',
  'appearance',
  'scheme',
  'viewport_width',
  'viewport_height',
  'insets',
  'is_layer',
] as const;

function newBlock(probe: string, label: string): ProbeBlock {
  return { probe, label, at: new Date().toISOString(), ok: true };
}

function safeSupports(bridge: BridgeLike, method: string): boolean | null {
  try {
    return bridge.supports(method);
  } catch {
    return null;
  }
}

async function vkCall(
  bridge: BridgeLike,
  method: string,
  params?: Record<string, unknown>,
): Promise<{ value: unknown } | { error: ErrorInfo }> {
  try {
    return { value: await bridge.send(method, params) };
  } catch (e) {
    return { error: toErrorInfo(e) };
  }
}

/** Probe A — «Среда»: environment snapshot, no side effects. */
export async function runEnvironmentProbe(
  bridge: BridgeLike,
  win: Window,
  doc: Document,
): Promise<ProbeBlock> {
  const block = newBlock('A', 'Среда');
  try {
    const launch = await vkCall(bridge, 'VKWebAppGetLaunchParams');
    const config = await vkCall(bridge, 'VKWebAppGetConfig');
    block.result = {
      metrics: collectMetrics(win, doc),
      bridge: {
        supportsResizeWindow: safeSupports(
          bridge,
          'VKWebAppResizeWindow',
        ),
        launchParams:
          'value' in launch
            ? pickWhitelisted(launch.value, LAUNCH_PARAM_KEYS)
            : { error: launch.error },
        config:
          'value' in config
            ? pickWhitelisted(config.value, CONFIG_KEYS)
            : { error: config.error },
      },
    };
  } catch (e) {
    block.ok = false;
    block.error = toErrorInfo(e);
  }
  return block;
}

/** Minimal fullscreen-capable target (Element or documentElement). */
export interface FullscreenTarget {
  requestFullscreen?: () => Promise<unknown>;
  webkitRequestFullscreen?: () => Promise<unknown>;
}

function describeElement(el: Element): string {
  const tag = el.tagName.toLowerCase();
  return el.id ? `${tag}#${el.id}` : tag;
}

/** Probes B (this block) and C (whole page): request fullscreen on `target`. */
export async function runFullscreenProbe(
  probe: 'B' | 'C',
  label: string,
  target: FullscreenTarget,
  win: Window,
  doc: Document,
  delayMs = 600,
): Promise<ProbeBlock> {
  const block = newBlock(probe, label);
  const events: string[] = [];
  const onChange = () => events.push('fullscreenchange');
  const onError = () => events.push('fullscreenerror');
  doc.addEventListener('fullscreenchange', onChange, { once: true });
  doc.addEventListener('fullscreenerror', onError, { once: true });
  try {
    const request =
      typeof target.requestFullscreen === 'function'
        ? target.requestFullscreen.bind(target)
        : typeof target.webkitRequestFullscreen === 'function'
          ? target.webkitRequestFullscreen.bind(target)
          : null;

    let call: 'unavailable' | 'resolved' | { rejected: ErrorInfo };
    let callError: ErrorInfo | null = null;
    if (request === null) {
      call = 'unavailable';
    } else {
      try {
        await request();
        call = 'resolved';
      } catch (e) {
        callError = toErrorInfo(e);
        call = { rejected: callError };
      }
    }

    if (delayMs > 0) {
      await delay(delayMs);
    }

    const el =
      doc.fullscreenElement ??
      (doc as Document & { webkitFullscreenElement?: Element | null })
        .webkitFullscreenElement ??
      null;

    block.result = {
      call,
      events,
      fullscreenElement: el ? describeElement(el) : null,
      metricsAfter: collectMetrics(win, doc),
    };
    if (callError) {
      block.ok = false;
      block.error = callError;
    }
  } catch (e) {
    block.ok = false;
    block.error = toErrorInfo(e);
  } finally {
    doc.removeEventListener('fullscreenchange', onChange);
    doc.removeEventListener('fullscreenerror', onError);
  }
  return block;
}

/** Probe D presets — order matters, the last one restores a sane size. */
export const RESIZE_PRESETS: ReadonlyArray<{
  width: number;
  height: number;
}> = [
  { width: 1000, height: 1200 },
  { width: 1000, height: 4050 },
  { width: 1400, height: 1200 },
  { width: 630, height: 600 },
  { width: 1000, height: 800 },
];

/** Probe D — VKWebAppResizeWindow with one preset size. */
export async function runResizeProbe(
  width: number,
  height: number,
  bridge: BridgeLike,
  win: Window,
  doc: Document,
  delayMs = 800,
): Promise<ProbeBlock> {
  const block = newBlock(
    'D',
    `Изменить размер окна ВК ${width}×${height}`,
  );
  let vkError: ErrorInfo | null = null;
  let resolved: unknown;
  try {
    resolved = await bridge.send('VKWebAppResizeWindow', { width, height });
  } catch (e) {
    vkError = toErrorInfo(e);
  }
  try {
    if (delayMs > 0) {
      await delay(delayMs);
    }
    block.result = {
      request: { width, height },
      ...(vkError ? {} : { resolved }),
      metricsAfter: collectMetrics(win, doc),
    };
    if (vkError) {
      block.ok = false;
      block.error = vkError;
    }
  } catch (e) {
    block.ok = false;
    block.error = vkError ?? toErrorInfo(e);
  }
  return block;
}

/** Probe E — open our own address in a top-level tab (child page). */
export function runOpenTabProbe(win: Window): ProbeBlock {
  const block = newBlock('E', 'Новая вкладка (наш адрес)');
  const url = `${win.location.origin}${win.location.pathname}${E1_PROBE_CHILD_HASH}`;
  const attempt = (features?: string): Record<string, unknown> => {
    try {
      const opened = features
        ? win.open(url, '_blank', features)
        : win.open(url, '_blank');
      return { returned: opened === null ? 'null' : 'window' };
    } catch (e) {
      return { threw: toErrorInfo(e) };
    }
  };
  try {
    block.result = {
      url: redactUrl(url),
      note: 'второй вызов без noopener: возврат null означает блокировку всплывающего окна',
      withNoopener: attempt('noopener'),
      withoutNoopener: attempt(),
    };
  } catch (e) {
    block.ok = false;
    block.error = toErrorInfo(e);
  }
  return block;
}

/** Probe F — open the app's own VK page (vk.com/app<id>) in a new tab. */
export async function runOpenVkAppProbe(
  bridge: BridgeLike,
  win: Window,
): Promise<ProbeBlock> {
  const block = newBlock('F', 'Новая вкладка (адрес приложения во ВК)');
  try {
    const launch = await bridge.send('VKWebAppGetLaunchParams');
    const appId = pickWhitelisted(launch, ['vk_app_id']).vk_app_id;
    if (typeof appId !== 'number' && typeof appId !== 'string') {
      block.ok = false;
      block.error = {
        name: 'MISSING_APP_ID',
        message: 'vk_app_id отсутствует в launch params',
      };
      return block;
    }
    const url = `https://vk.com/app${appId}`;
    let outcome: Record<string, unknown>;
    try {
      const opened = win.open(url, '_blank');
      outcome = { returned: opened === null ? 'null' : 'window' };
    } catch (e) {
      outcome = { threw: toErrorInfo(e) };
    }
    block.result = { vk_app_id: appId, url, ...outcome };
  } catch (e) {
    block.ok = false;
    block.error = toErrorInfo(e);
  }
  return block;
}
