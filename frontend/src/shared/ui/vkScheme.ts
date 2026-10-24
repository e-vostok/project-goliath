/**
 * VK scheme listener (UI Spec 5.4) — the only place vk-bridge enters
 * the theme mechanism.
 *
 * ThemeProvider pulls this module through a dynamic import and only
 * when `listenVkScheme` is on, so bundles that never run inside VK
 * (the standalone /admin.html panel page) neither statically import
 * vk-bridge nor ever fetch this chunk.
 */

import bridge from '@vkontakte/vk-bridge';

function readConfigScheme(config: unknown): string | null {
  const scheme = (config as { scheme?: unknown } | null)?.scheme;
  return typeof scheme === 'string' && scheme ? scheme : null;
}

/**
 * Ask VK for its scheme once and keep listening for changes; outside
 * VK both calls simply never answer (Spec 5.4 — «не проверено»).
 * Returns the unsubscribe function.
 */
export function subscribeVkScheme(
  onScheme: (scheme: string) => void,
): () => void {
  const onBridgeEvent = (event: {
    detail?: { type?: string; data?: unknown };
  }) => {
    try {
      if (event?.detail?.type === 'VKWebAppUpdateConfig') {
        const scheme = readConfigScheme(event.detail.data);
        if (scheme) {
          onScheme(scheme);
        }
      }
    } catch {
      // A malformed bridge event must never break the theme.
    }
  };
  bridge.subscribe(onBridgeEvent);
  void bridge
    .send('VKWebAppGetConfig')
    .then((config) => {
      const scheme = readConfigScheme(config);
      if (scheme) {
        onScheme(scheme);
      }
    })
    .catch(() => {});
  return () => {
    try {
      bridge.unsubscribe(onBridgeEvent);
    } catch {
      // Bridge may already be gone — nothing to undo.
    }
  };
}
