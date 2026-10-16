import '@testing-library/jest-dom/vitest';
import { setupServer } from 'msw/node';

import { clearAllFormDrafts } from './src/shared/formDraft';

export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  // Form drafts are module-level session state — never leak them
  // between tests.
  clearAllFormDrafts();
});
afterAll(() => server.close());

// jsdom lacks browser APIs that VKUI touches at runtime.
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

if (!global.ResizeObserver) {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

window.scrollTo = () => {};
