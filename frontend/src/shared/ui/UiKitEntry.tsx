/**
 * UiKitEntry — the `#ui-kit` catalogue entry. Sends `VKWebAppInit` in a
 * layout effect, which lands ahead of the children's passive effects —
 * the handshake reaches VK before ThemeProvider asks
 * `VKWebAppGetConfig`.
 */

import { useLayoutEffect } from 'react';

import { sendVkInit } from '../vkInit';
import { ThemeProvider } from './theme';
import { UiKitPage } from './UiKitPage';

export function UiKitEntry() {
  useLayoutEffect(() => {
    sendVkInit();
  }, []);
  return (
    <ThemeProvider>
      <UiKitPage />
    </ThemeProvider>
  );
}
