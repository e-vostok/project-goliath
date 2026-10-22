/**
 * tooltip-follow-probe.mjs — real-browser check of «Подсказка»
 * cursor following (unit 12b, Project Owner report 21.10.2026).
 *
 * Opens the Registry on a local vite dev server with fixture data
 * (all /api/v1/* calls intercepted by page.route — no backend),
 * hovers a nation cell with page.mouse.move, waits 600 ms, then moves
 * the pointer 120 px right and 40 px down in steps, recording the
 * tooltip rect after every step. Verdict: while the tip is open its
 * rect must sit within 40 px of (cursor + offset).
 *
 * Playwright is NOT a project dependency — the script resolves it
 * from the npx cache (`npx playwright` was run once on this machine)
 * or from PLAYWRIGHT_NODE_MODULES. Browser: system Chrome
 * (channel 'chrome') — no `playwright install` needed.
 *
 * Run from the repo root:
 *   node tools/tooltip-follow-probe.mjs
 * The script starts `npx vite` on :5199 itself and kills it on exit.
 * Artifacts (screenshot + JSON trace) land in tools/artifacts/.
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import https from 'node:https';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..');
const FRONTEND = join(REPO, 'frontend');
const ARTIFACTS = join(HERE, 'artifacts');
const PORT = Number(process.env.PROBE_PORT ?? 5199);
// vite.config.ts uses @vitejs/plugin-basic-ssl — the dev server is HTTPS.
const BASE = `https://127.0.0.1:${PORT}`;

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
  throw new Error(
    'playwright not found — run `npx playwright --version` once so it lands in the npx cache, or set PLAYWRIGHT_NODE_MODULES.',
  );
}

const { chromium } = resolvePlaywright();

/* ------------------------------------------------- map fixtures */

// The mini map fixture is TS — transpile it in place with the
// frontend's own esbuild so the probe serves the real test map.
const requireFrontend = createRequire(join(FRONTEND, 'package.json'));
const esbuild = requireFrontend('esbuild');
const mapSource = readFileSync(
  join(FRONTEND, 'src/modules/01_map/fixtures/miniMap.ts'),
  'utf8',
);
const mapModule = { exports: {} };
new Function(
  'module',
  'exports',
  esbuild.transformSync(mapSource, { loader: 'ts', format: 'cjs' }).code,
)(
  mapModule,
  mapModule.exports,
);
const { MINI_MANIFEST, MINI_GEOMETRY, MINI_BORDERS, MINI_STATE } =
  mapModule.exports;

/* ------------------------------------------------- API fixtures */

const PLAYER = {
  id: '3f6b5d28-8f6d-4b7e-9a1c-2e5f7a9b0c1d',
  vk_user_id: 123456,
  created_at: '2026-09-01T12:00:00Z',
};
const NATION_ID = 'a1b2c3d4-0000-4b7e-9a1c-2e5f7a9b0c1d';
const NATION_PUBLIC = {
  id: NATION_ID,
  created_at: '2026-09-01T12:00:00Z',
  name: 'Новгород',
  short_name: 'НВГ',
  color_hex: '#C0392B',
  motto: 'Слово и дело',
  description: 'Вольный город на севере.',
  flag_id: null,
  flag_url: null,
  province_ids: [1001, 1002],
  capital_province_id: 1001,
  capital_name: 'Новгород-град',
  leader_name: 'Борис Первый',
  leader_title: 'Князь',
  leader_bio: null,
  portrait_id: null,
  portrait_url: null,
  history_url: null,
  level: 3,
  judge_rating: 12,
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
  min_provinces: 3,
  max_provinces: 3,
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
        { id: 'level', title: 'Уровень', type: 'integer', width_px: 92, sortable: true, filters: ['number_range'], filter_label: null, header_icon: null, searchable: false, stub: true, scale_min: null, scale_max: null },
        { id: 'nation', title: 'Государство', type: 'nation', width_px: 292, sortable: true, filters: ['select_or_contains', 'presence'], filter_label: null, header_icon: null, searchable: true, stub: false, scale_min: null, scale_max: null },
      ],
    },
    {
      id: 'nations',
      title: 'Государства',
      icon: 'nations',
      empty_text: 'Государств пока нет',
      default_sort: { column: 'number', direction: 'asc' },
      columns: [
        { id: 'number', title: '№', type: 'index', width_px: 48, sortable: true, filters: [], filter_label: null, header_icon: null, searchable: false, stub: false, scale_min: null, scale_max: null },
        { id: 'name', title: 'Название', type: 'text', width_px: 430, sortable: true, filters: ['text'], filter_label: null, header_icon: null, searchable: true, stub: false, scale_min: null, scale_max: null },
        { id: 'formed', title: 'Дата формирования', type: 'date', width_px: 176, sortable: true, filters: ['number_range'], filter_label: 'Ход', header_icon: null, searchable: false, stub: false, scale_min: null, scale_max: null },
      ],
    },
  ],
};
const PLAYERS_ROWS = {
  table_id: 'players',
  total: 3,
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
        nation: { id: NATION_ID, name: 'Новгород', color: '#C0392B', flag_url: null },
      },
    },
    {
      key: 'p2',
      cells: {
        number: 2,
        player: { name: 'Анна Смирнова', avatar_url: null, is_fallback: false },
        joined: { text: '5 сентября 2026', key: 20701 },
        level: 2,
        nation: null,
      },
    },
    {
      key: 'p3',
      cells: {
        number: 3,
        player: { name: 'Игрок №3', avatar_url: null, is_fallback: true },
        joined: { text: '10 сентября 2026', key: 20706 },
        level: 1,
        nation: { id: 'n2', name: 'Рязань', color: '#2980B9', flag_url: null },
      },
    },
  ],
};
const NATIONS_ROWS = {
  table_id: 'nations',
  total: 2,
  truncated: false,
  generated_at: '2026-10-14T10:00:00Z',
  rows: [
    { key: NATION_ID, cells: { number: 1, name: 'Новгород', formed: { text: 'Январь 2041', key: 12 } } },
    { key: 'n2', cells: { number: 2, name: 'Рязань', formed: { text: 'Май 2043', key: 40 } } },
  ],
};

function json(route, body) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

async function stubApi(page) {
  // Catch-all first: nothing leaves the machine (flag/avatar URLs,
  // vk-bridge fallbacks); local vite traffic defers to the network.
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (url.startsWith(BASE) || url.startsWith('data:') || url.startsWith('blob:')) {
      return route.fallback();
    }
    return route.abort();
  });
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path.endsWith('/auth/vk') && method === 'POST') {
      return json(route, { access_token: 'jwt-token-abc', token_type: 'bearer', expires_in: 3600, player: PLAYER });
    }
    if (path.endsWith('/nations/me')) {
      return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Nation not found', code: 'NATION_NOT_FOUND' }) });
    }
    if (path.endsWith('/nations/rules')) return json(route, RULES);
    if (path.endsWith('/provinces')) return json(route, [{ id: 1003, nation_id: null }]);
    if (path.endsWith('/bot/status')) {
      return json(route, { enabled: false, consent: 'UNKNOWN', stale: false, throttled: false, registration_requires_consent: false, chat_url: null, consent_poll_interval_seconds: null, consent_poll_timeout_seconds: null });
    }
    if (path.endsWith('/admin/me')) return json(route, { is_admin: false });
    if (path.endsWith('/game-clock')) {
      return json(route, { current_turn: 12, game_date: '2041-01-01', game_date_text: 'Январь 2041', next_tick_at: '2026-10-15T03:00:00Z' });
    }
    if (path.endsWith('/map/manifest')) return json(route, MINI_MANIFEST);
    if (path.includes('/map/geometry/')) return json(route, MINI_GEOMETRY);
    if (path.includes('/map/borders/')) return json(route, MINI_BORDERS);
    if (path.endsWith('/map/state')) return json(route, MINI_STATE);
    if (path.endsWith('/registry/tables')) return json(route, TABLES);
    if (path.endsWith('/registry/tables/players')) return json(route, PLAYERS_ROWS);
    if (path.endsWith('/registry/tables/nations')) return json(route, NATIONS_ROWS);
    if (/^\/api\/v1\/nations\/[^/]+$/.test(path)) return json(route, NATION_PUBLIC);
    return json(route, {});
  });
}

/* ------------------------------------------------- vite server */

let vite = null;

function startVite() {
  return new Promise((resolve, reject) => {
    // The vite bin directly (no npx/shell wrapper — killing this child
    // kills the server).
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
    vite.on('exit', (code) => {
      if (!settled) reject(new Error(`vite exited early: ${code}`));
    });
    setTimeout(probe, 300);
    setTimeout(() => {
      if (!settled) reject(new Error('vite did not come up in 30 s'));
    }, 30000);
  });
}

/* ------------------------------------------------------ probe */

const tip = async (page) =>
  page.evaluate(() => {
    const el = document.querySelector('[data-testid="tooltip"]');
    if (el === null) return null;
    const r = el.getBoundingClientRect();
    const visible = getComputedStyle(el).visibility !== 'hidden';
    return { left: r.left, top: r.top, width: r.width, height: r.height, visible };
  });

async function main() {
  mkdirSync(ARTIFACTS, { recursive: true });
  console.log('starting vite…');
  await startVite();
  console.log(`vite up on ${BASE}`);

  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    const context = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      ignoreHTTPSErrors: true, // the dev server's self-signed cert
    });
    const page = await context.newPage();
    await stubApi(page);
    page.on('pageerror', (e) => console.log('[pageerror]', String(e)));

    await page.goto(`${BASE}/#/registry`, { waitUntil: 'domcontentloaded' });
    // Registry rows + the nation cell button are up.
    const cell = page.getByRole('button', { name: 'Новгород' }).first();
    await cell.waitFor({ state: 'visible', timeout: 15000 });
    await page.waitForTimeout(400); // settle: tip fetch, layout

    const box = await cell.boundingBox();
    if (box === null) throw new Error('nation cell has no box');
    // The trigger wrapper is the span around the button.
    const triggerRect = await cell.evaluate((el) => {
      const t = el.parentElement.getBoundingClientRect();
      const td = el.closest('td').getBoundingClientRect();
      return { trigger: { x: t.x, y: t.y, w: t.width, h: t.height }, td: { x: td.x, y: td.y, w: td.width, h: td.height } };
    });
    console.log('trigger span rect:', JSON.stringify(triggerRect.trigger));
    console.log('cell (td) rect:   ', JSON.stringify(triggerRect.td));

    const x0 = box.x + 14;
    const y0 = box.y + box.height / 2;
    await page.mouse.move(x0, y0);
    await page.waitForTimeout(600); // delay is 500 ms
    const opened = await tip(page);
    console.log('tip after 600 ms hover:', JSON.stringify(opened));
    if (opened === null || !opened.visible) {
      console.log('FAIL: tooltip did not open after the hover delay');
      process.exitCode = 1;
      return;
    }

    // Prescribed move: +120 px right, +40 px down, in steps; the rect
    // is sampled after every step while the tip stays open.
    const STEPS = 12;
    const samples = [{ x: x0, y: y0, tip: opened }];
    for (let i = 1; i <= STEPS; i++) {
      const cx = x0 + (120 * i) / STEPS;
      const cy = y0 + (40 * i) / STEPS;
      await page.mouse.move(cx, cy);
      await page.waitForTimeout(70); // a few frames
      const t = await tip(page);
      samples.push({ x: cx, y: cy, tip: t });
      // Evidence: the tip mid-move, still open and beside the cursor.
      if (t !== null && i === 4) {
        mkdirSync(ARTIFACTS, { recursive: true });
        await page.screenshot({
          path: join(ARTIFACTS, 'tooltip-tracking.png'),
        });
      }
      console.log(
        `step ${String(i).padStart(2)}: cursor=(${cx.toFixed(0)},${cy.toFixed(0)})`,
        t === null ? 'tip: closed' : `tip: left=${t.left.toFixed(1)} top=${t.top.toFixed(1)}`,
      );
    }

    mkdirSync(ARTIFACTS, { recursive: true });
    await page.screenshot({ path: join(ARTIFACTS, 'tooltip-after-move.png') });
    writeFileSync(join(ARTIFACTS, 'tooltip-trace.json'), JSON.stringify({ triggerRect, samples }, null, 2));

    // Verdict: every step while the tip stayed open must land within
    // 40 px of cursor + offset (+12/+16); clamping only ever moves it
    // closer to the cursor.
    let tracked = 0;
    for (const s of samples.slice(1)) {
      if (s.tip === null) continue;
      tracked += 1;
      const dLeft = s.tip.left - (s.x + 12);
      const dTop = s.tip.top - (s.y + 16);
      const okLeft = dLeft >= -40 && dLeft <= 40;
      // The tip may flip ABOVE the pointer near the container bottom.
      const dTopFlip = s.tip.top - (s.y - 16 - s.tip.height);
      const okTop = Math.abs(dTop) <= 40 || Math.abs(dTopFlip) <= 40;
      if (!okLeft || !okTop) {
        console.log(`FAIL: at (${s.x.toFixed(0)},${s.y.toFixed(0)}) tip at (${s.tip.left.toFixed(1)},${s.tip.top.toFixed(1)}) is >40px off cursor+offset`);
        process.exitCode = 1;
        return;
      }
    }

    const lastOpen = [...samples].reverse().find((s) => s.tip !== null);
    const endStillOpen = samples[samples.length - 1].tip !== null;
    if (tracked === 0) {
      console.log('FAIL: tooltip never tracked the move (closed instantly)');
      process.exitCode = 1;
      return;
    }
    console.log(
      `tip tracked ${tracked}/${STEPS} steps; last open position near cursor (${lastOpen.x.toFixed(0)},${lastOpen.y.toFixed(0)})` +
        (endStillOpen ? '; still open at the end' : `; closed when the pointer left the trigger`),
    );
    console.log('PASS: the tooltip follows the cursor in a real browser');
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
