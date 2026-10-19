/**
 * The vk-bridge handshake, in one place. `VKWebAppInit` must fire once
 * on every entry path — the normal app and the hidden `#ui-kit`
 * catalogue alike; without it VK shows its loading spinner forever.
 * Idempotent: later calls are ignored, the handshake goes out once.
 */

import bridge from '@vkontakte/vk-bridge';

let sent = false;

export function sendVkInit(): void {
  if (sent) {
    return;
  }
  sent = true;
  void bridge.send('VKWebAppInit').catch(() => {});
}
