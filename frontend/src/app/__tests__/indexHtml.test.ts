/**
 * index.html entry preloads (load-speed unit 10, proposal 5): exactly
 * the two brand fonts that prevent the FOUT jump on the loading screen
 * and the nation card — Big Shoulders Display 800 and Fira Sans
 * Condensed Medium — and nothing else. Every preload href must resolve
 * to a real file under frontend/public/.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const FRONTEND_ROOT = resolve(__dirname, '..', '..', '..');
const PUBLIC_ROOT = join(FRONTEND_ROOT, 'public');

const EXPECTED_FONT_PRELOADS = [
  '/assets/fonts/bigshouldersdisplay-800.woff2',
  '/assets/fonts/firasanscondensed-medium.woff2',
];

function fontPreloadHrefs(html: string): string[] {
  const links = html.match(/<link\b[^>]*>/g) ?? [];
  return links
    .filter(
      (tag) => /\brel="preload"/.test(tag) && /\bas="font"/.test(tag),
    )
    .map((tag) => /\bhref="([^"]+)"/.exec(tag)?.[1] ?? '');
}

describe('index.html — font preloads', () => {
  const html = readFileSync(join(FRONTEND_ROOT, 'index.html'), 'utf8');
  const hrefs = fontPreloadHrefs(html);

  it('preloads exactly the two brand fonts', () => {
    expect(hrefs).toEqual(EXPECTED_FONT_PRELOADS);
  });

  it('every preload carries crossorigin and the woff2 type', () => {
    const links = html.match(/<link\b[^>]*>/g) ?? [];
    const fontLinks = links.filter(
      (tag) => /\brel="preload"/.test(tag) && /\bas="font"/.test(tag),
    );
    for (const tag of fontLinks) {
      expect(tag).toContain('crossorigin');
      expect(tag).toContain('type="font/woff2"');
    }
  });

  it('every preloaded href is a real file in public/', () => {
    for (const href of hrefs) {
      expect(existsSync(join(PUBLIC_ROOT, href)), href).toBe(true);
    }
  });
});
