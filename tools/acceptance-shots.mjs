/**
 * acceptance-shots.mjs — screenshot set for the 0.9.0 unit 12b
 * acceptance round: card header («Кратко:» variants), territory
 * chips, the ProvincePicker info row with 0 and 5 provinces, the
 * Loading and auth-error screens — each in dark and light themes.
 *
 * No backend: every /api/v1/* call is intercepted by page.route and
 * answered with the mini-map + registry fixtures. Browser: system
 * Chrome (channel 'chrome'); Playwright resolves from the npx cache —
 * same as tooltip-follow-probe.mjs.
 *
 *   node tools/acceptance-shots.mjs
 *
 * Output: tools/artifacts/shots/*.png
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import https from 'node:https';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..');
const FRONTEND = join(REPO, 'frontend');
const OUT = join(HERE, 'artifacts', 'shots');
const PORT = Number(process.env.SHOTS_PORT ?? 5198);
const BASE = `https://127.0.0.1:${PORT}`; // vite dev is HTTPS (basic-ssl)

/* -------------------------------------------------- playwright */

function resolvePlaywright() {
  const candidates = [];
  if (process.env.PLAYWRIGHT_NODE_MODULES) {
    candidates.push(process.env.PLAYWRIGHT_NODE_MODULES);
  }
  const npxCache = join(
    process.env.LOCALAPPDATA ?? join(process.env.HOME ?? '', '.cache'),
    'npm-cache',
    '_npx',
  );
  if (existsSync(npxCache)) {
    for (const dir of readdirSync(npxCache)) {
      candidates.push(join(npxCache, dir, 'node_modules'));
    }
  }
  candidates.push(join(FRONTEND, 'node_modules'));
  for (const root of candidates) {
    if (existsSync(join(root, 'playwright', 'package.json'))) {
      return createRequire(join(root, 'index.js'))('playwright');
    }
  }
  throw new Error('playwright not found in npx cache / node_modules');
}
const { chromium } = resolvePlaywright();

/* ------------------------------------------------- map fixtures */

const requireFrontend = createRequire(join(FRONTEND, 'package.json'));
const esbuild = requireFrontend('esbuild');
const mapModule = { exports: {} };
new Function(
  'module',
  'exports',
  esbuild.transformSync(
    readFileSync(
      join(FRONTEND, 'src/modules/01_map/fixtures/miniMap.ts'),
      'utf8',
    ),
    { loader: 'ts', format: 'cjs' },
  ).code,
)(mapModule, mapModule.exports);
const { MINI_MANIFEST, MINI_GEOMETRY, MINI_BORDERS, MINI_STATE } =
  mapModule.exports;

/* ------------------------------------------------- API fixtures */

const PLAYER = {
  id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
  vk_user_id: 123456,
  created_at: '2026-09-01T12:00:00Z',
};
const NATION_ID = 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d';
const EQUAL_ID = 'b2c3d4e5-1111-4b7e-9a1c-2e5f7a9b0c1e';
const NATION_PUBLIC = {
  id: NATION_ID,
  created_at: '2026-09-01T12:00:00Z',
  name: 'Новгородская республика вольная',
  short_name: 'НВГ',
  color_hex: '#C0392B',
  motto: 'Слово и дело',
  description: 'Вольный город на севере.',
  flag_id: null,
  flag_url: null,
  province_ids: [1001, 1002, 1003],
  capital_province_id: 1001,
  capital_name: 'Новгород-град-на-волге-большой',
  leader_name: 'Борис Первый',
  leader_title: 'Князь',
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  history_url: null,
  level: 3,
  judge_rating: 12,
};
const NATION_EQUAL = {
  ...NATION_PUBLIC,
  id: EQUAL_ID,
  short_name: 'Новгородская республика вольная',
};
const RULES = {
  name_min_length: 4,
  name_max_length: 37,
  short_name_min_length: 3,
  short_name_max_length: 15,
  motto_max_length: 55,
  description_max_length: 111,
  leader_name_min_length: 2,
  leader_name_max_length: 33,
  leader_title_min_length: 3,
  leader_title_max_length: 44,
  leader_bio_max_length: 444,
  capital_name_min_length: 2,
  capital_name_max_length: 22,
  history_url_max_length: 321,
  history_url_allowed_hosts: ['vk.com'],
  anthem_url_max_length: 222,
  anthem_url_allowed_hosts: ['vk.com'],
  min_provinces: 1,
  max_provinces: 6,
  palette: ['#102030'],
  flags: [],
  portraits: [],
  genders: ['male', 'female'],
  succession_types: ['elections'],
};
const TABLES = {
  layout: { tabs_position: 'top' },
  tables: [
    {
      id: 'players',
      title: 'Игроки',
      icon: 'players',
      empty_text: 'Игроков пока нет',
      default_sort: { column: 'number', direction: 'asc' },
      columns: [
        { id: 'number', title: '№', type: 'index', width_px: 48, sortable: true, filters: [], filter_label: null, header_icon: null, searchable: false, stub: false, scale_min: null, scale_max: null },
        { id: 'player', title: 'Игрок', type: 'person', width_px: 190, sortable: true, filters: ['text'], filter_label: null, header_icon: null, searchable: true, stub: false, scale_min: null, scale_max: null },
        { id: 'joined', title: 'Дата регистрации', type: 'date', width_px: 136, sortable: true, filters: ['date_range'], filter_label: null, header_icon: null, searchable: false, stub: false, scale_min: null, scale_max: null },
        { id: 'nation', title: 'Государство', type: 'nation', width_px: 292, sortable: true, filters: [], filter_label: null, header_icon: null, searchable: true, stub: false, scale_min: null, scale_max: null },
      ],
    },
  ],
};
const PLAYERS_ROWS = {
  table_id: 'players',
  total: 1,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    {
      key: 'p1',
      cells: {
        number: 1,
        player: { name: 'Борис Иванов', avatar_url: null, is_fallback: false },
        joined: { text: '1 сентября 2026', key: 20697 },
        level: 1,
        nation: { id: NATION_ID, name: 'Новгородская республика вольная', color: '#C0392B', flag_url: null },
      },
    },
  ],
};

const json = (route, body) =>
  route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });

/**
 * @param page playwright Page
 * @param auth 'ok' | 'pending' | 'fail'
 */
async function stubApi(page, auth = 'ok') {
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (
      url.startsWith(BASE) ||
      url.startsWith('data:') ||
      url.startsWith('blob:')
    ) {
      return route.fallback();
    }
    return route.abort();
  });
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path.endsWith('/auth/vk') && method === 'POST') {
      if (auth === 'pending') {
        return new Promise(() => {}); // never resolves → the gate stays
      }
      if (auth === 'fail') {
        return route.fulfill({
          status: 403,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'bad signature' }),
        });
      }
      return json(route, {
        access_token: 'jwt-token-abc',
        token_type: 'bearer',
        expires_in: 3600,
        player: PLAYER,
      });
    }
    if (path.endsWith('/nations/me')) {
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: 'Nation not found',
          code: 'NATION_NOT_FOUND',
        }),
      });
    }
    if (path.endsWith('/nations/rules')) return json(route, RULES);
    if (path.endsWith('/provinces')) return json(route, []);
    if (path.endsWith('/bot/status')) {
      return json(route, {
        enabled: false,
        consent: 'UNKNOWN',
        stale: false,
        throttled: false,
        registration_requires_consent: false,
        chat_url: null,
        consent_poll_interval_seconds: null,
        consent_poll_timeout_seconds: null,
      });
    }
    if (path.endsWith('/admin/me')) return json(route, { is_admin: false });
    if (path.endsWith('/game-clock')) {
      return json(route, {
        current_turn: 12,
        game_date: '2041-01-01',
        game_date_text: 'Январь 2041',
        next_tick_at: '2026-10-15T03:00:00Z',
      });
    }
    if (path.endsWith('/map/manifest')) return json(route, MINI_MANIFEST);
    if (path.includes('/map/geometry/')) return json(route, MINI_GEOMETRY);
    if (path.includes('/map/borders/')) return json(route, MINI_BORDERS);
    if (path.endsWith('/map/state')) return json(route, MINI_STATE);
    if (path.endsWith('/registry/tables')) return json(route, TABLES);
    if (path.endsWith('/registry/tables/players')) {
      return json(route, PLAYERS_ROWS);
    }
    if (path.endsWith(`/nations/${NATION_ID}`)) {
      return json(route, NATION_PUBLIC);
    }
    if (path.endsWith(`/nations/${EQUAL_ID}`)) {
      return json(route, NATION_EQUAL);
    }
    if (/^\/api\/v1\/nations\/[^/]+$/.test(path)) {
      return json(route, NATION_PUBLIC);
    }
    return json(route, {});
  });
}

/* ------------------------------------------------- vite server */

let vite = null;
function startVite() {
  return new Promise((resolve, reject) => {
    vite = spawn(
      process.execPath,
      [
        join(FRONTEND, 'node_modules/vite/bin/vite.js'),
        '--port',
        String(PORT),
        '--strictPort',
        '--clearScreen',
        'false',
        '--host',
        '127.0.0.1',
      ],
      { cwd: FRONTEND, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    vite.stderr.on('data', (d) => process.stderr.write(`[vite] ${d}`));
    let settled = false;
    const probe = () => {
      https
        .get(`${BASE}/`, { rejectUnauthorized: false }, (res) => {
          res.resume();
          if (!settled) {
            settled = true;
            resolve();
          }
        })
        .on('error', () => setTimeout(probe, 250));
    };
    vite.on('error', reject);
    setTimeout(probe, 300);
    setTimeout(() => {
      if (!settled) reject(new Error('vite did not come up in 30 s'));
    }, 30000);
  });
}

/* -------------------------------------------------------- shots */

async function shot(page, name) {
  const path = join(OUT, `${name}.png`);
  await page.screenshot({ path });
  console.log(`  ${name}.png`);
}

async function newPage(browser, theme, auth = 'ok') {
  const context = await browser.newContext({
    viewport: { width: 910, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  await page.addInitScript((t) => window.localStorage.setItem('pax.theme', t), theme);
  await stubApi(page, auth);
  page.on('pageerror', (e) => console.log('[pageerror]', String(e)));
  return { context, page };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  console.log('starting vite…');
  await startVite();
  console.log(`vite up on ${BASE}`);

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
  });
  try {
    for (const theme of ['dark', 'light']) {
      console.log(`theme: ${theme}`);

      // 1. Loading gate — auth never resolves.
      {
        const { context, page } = await newPage(browser, theme, 'pending');
        await page.goto(`${BASE}/#/`, { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('[data-testid="loading-screen"]');
        await page.waitForTimeout(500);
        await shot(page, `loading-${theme}`);
        await context.close();
      }

      // 2. Auth error — the «Ошибка» surface card.
      {
        const { context, page } = await newPage(browser, theme, 'fail');
        await page.goto(`${BASE}/#/`, { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('[data-testid="auth-error-screen"]');
        await page.waitForTimeout(300);
        await shot(page, `auth-error-${theme}`);
        await context.close();
      }

      // 3–4. Nation subscreen — «Кратко:» shown / hidden.
      for (const [id, tag] of [
        [NATION_ID, 'different'],
        [EQUAL_ID, 'equal'],
      ]) {
        const { context, page } = await newPage(browser, theme);
        await page.goto(`${BASE}/#/registry/nation-${id}`, {
          waitUntil: 'domcontentloaded',
        });
        const header = page.locator('[data-testid="nation-card-header"]');
        await header.waitFor({ state: 'visible', timeout: 15000 });
        // Territory names resolve through the manifest — wait for chips.
        await page.waitForSelector(
          '[data-testid="nation-territory-block"] [data-testid="province-chip"]',
        );
        await page.waitForTimeout(300);
        await shot(
          page,
          `card-header-${tag}-${theme}`,
        );
        await context.close();
      }

      // 5. Territory block close-up (the different-short-name card).
      {
        const { context, page } = await newPage(browser, theme);
        await page.goto(`${BASE}/#/registry/nation-${NATION_ID}`, {
          waitUntil: 'domcontentloaded',
        });
        const block = page.locator(
          '[data-testid="nation-territory-block"]',
        );
        await page.waitForSelector(
          '[data-testid="nation-territory-block"] [data-testid="province-chip"]',
        );
        await page.waitForTimeout(300);
        await block.screenshot({
          path: join(OUT, `territory-${theme}.png`),
        });
        console.log(`  territory-${theme}.png`);
        await context.close();
      }

      // 6. ProvincePicker — 0 and 5 selected, info row stable.
      {
        const { context, page } = await newPage(browser, theme);
        await page.goto(`${BASE}/#/nation/new`, {
          waitUntil: 'domcontentloaded',
        });
        await page.waitForSelector('[data-testid="step-title-4"]', {
          timeout: 15000,
        });
        await page.locator('[data-testid="step-title-4"]').click();
        await page
          .getByTestId('open-province-picker')
          .click();
        await page.waitForSelector(
          '[data-testid="picker-map"] path[data-id]',
          { timeout: 15000 },
        );
        await page.waitForTimeout(400);
        const picker = page.locator('[data-testid="province-picker"]');
        await picker.screenshot({
          path: join(OUT, `picker-0-${theme}.png`),
        });
        console.log(`  picker-0-${theme}.png`);

        // Selection is mousedown on the path + mouseup on window —
        // dispatch the same pair the unit tests use (a real click
        // point can fall under the chips strip for tiny paths).
        for (const id of [1003, 1004, 1005, 1006, 1007]) {
          await page
            .locator(`path[data-id="${id}"]`)
            .dispatchEvent('mousedown', { button: 0 });
          await page.evaluate(() =>
            window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })),
          );
        }
        await page.waitForTimeout(400);
        await picker.screenshot({
          path: join(OUT, `picker-5-${theme}.png`),
        });
        console.log(`  picker-5-${theme}.png`);
        await context.close();
      }
    }
    console.log('done');
  } finally {
    await browser.close();
    if (vite) vite.kill('SIGTERM');
  }
}

main().catch((error) => {
  console.error(error);
  if (vite) vite.kill('SIGTERM');
  process.exit(1);
});
