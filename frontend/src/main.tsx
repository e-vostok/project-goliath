/**
 * Frontend entry point — VK Mini App shell.
 *
 * - VKWebAppInit() fires exactly once on mount (vk-bridge handshake).
 * - VKUI is pinned to a desktop presentation: Platform.VKCOM + fixed
 *   ViewWidth.DESKTOP adaptivity (project is Desktop-Only by design —
 *   1920×1080, mouse/keyboard; no smartphone breakpoints).
 * - Hash routing: vk-mini-apps-router over two panels of the main view.
 */

import { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import bridge from '@vkontakte/vk-bridge';
import {
  AdaptivityProvider,
  AppRoot,
  ConfigProvider,
  Platform,
  ViewWidth,
} from '@vkontakte/vkui';
import {
  createHashRouter,
  RouterProvider,
} from '@vkontakte/vk-mini-apps-router';

import { AppShell, PANEL_CREATE, PANEL_HOME } from './app/AppShell';

import '@vkontakte/vkui/dist/vkui.css';

const router = createHashRouter([
  { path: '/', panel: PANEL_HOME, view: 'main' },
  { path: '/nation/new', panel: PANEL_CREATE, view: 'main' },
]);

function App() {
  useEffect(() => {
    void bridge.send('VKWebAppInit').catch(() => {});
  }, []);

  return (
    <ConfigProvider platform={Platform.VKCOM}>
      <AdaptivityProvider viewWidth={ViewWidth.DESKTOP}>
        <AppRoot>
          <RouterProvider router={router}>
            <AppShell />
          </RouterProvider>
        </AppRoot>
      </AdaptivityProvider>
    </ConfigProvider>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
