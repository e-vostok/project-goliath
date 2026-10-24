/**
 * Admin panel entry point (`/admin.html`) — a bare browser tab, NOT a
 * VK Mini App: no vk-bridge handshake, no launch params, no VKUI
 * shell. The theme mechanism is reused with `listenVkScheme=false`,
 * so vk-bridge is neither imported nor asked for a scheme here.
 */

import { createRoot } from 'react-dom/client';

import { ThemeProvider } from '../shared/ui/theme';
import { AdminApp } from './AdminApp';

import '../shared/ui/fonts.css';
import './admin.css';

createRoot(document.getElementById('root')!).render(
  <ThemeProvider listenVkScheme={false}>
    <AdminApp />
  </ThemeProvider>,
);
