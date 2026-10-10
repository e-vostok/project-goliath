/**
 * map_pan.mjs — frame-time benchmark for the 01_map screen (map2_12).
 *
 * Serves a BUILT client (vite build output) on a local port together
 * with a tiny stub of /api/v1/* that answers the real map files
 * (data/map/manifest.json + rules from configs/01_map.yaml, geometry,
 * borders, an empty state). A scripted mouse drag and a scripted wheel
 * zoom are then driven through Playwright while requestAnimationFrame
 * deltas are recorded inside the page.
 *
 * Usage:
 *   node tools/perf/map_pan.mjs --dist frontend/dist [--tag main]
 *     [--variant base|no-borders|no-internal|no-labels|no-seam|no-nss|no-pulse|all-off]
 *     [--runs 2] [--throttle 4] [--headed] [--json out.json]
 *
 * Requires the playwright package (not a repo dependency): either
 * `npm i -g playwright` (resolved via `npm root -g`) or
 * PLAYWRIGHT_MODULE=/path/to/playwright. Uses the preinstalled Chrome
 * (channel 'chrome', falls back to 'msedge', then the bundled build).
 *
 * Scenarios (cumulative wheel notches from z = 1, step ×1.25):
 *   out  = 1 notch  (≈ whole map, small pan band)
 *   med  = 5 notches (z ≈ 3.0)
 *   high = 10 notches (z ≈ 9.3, zoom_max is 10.8)
 * Each scenario records the zoom burst that reaches it, then a
 * two-leg drag; deltas are merged across --runs.
 *
 * A land node is clicked first so the selection overlay (the pulse in
 * view mode) is active during every measurement, like real usage.
 */

import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const DATA = join(ROOT, 'data', 'map');

/* ------------------------------------------------------------ args */

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
}
const DIST = resolve(opt('dist', 'frontend/dist'));
const TAG = opt('tag', DIST);
const VARIANT = opt('variant', 'base');
const RUNS = Number(opt('runs', '2'));
const THROTTLE = Number(opt('throttle', '4'));
const HEADED = args.includes('--headed');
const JSON_OUT = opt('json', null);

/* ------------------------------------------------- API stub data */

// Mirrors configs/01_map.yaml `view`/`hover`/`borders`/`selection`/
// `colors`/`refresh`/`big_window` blocks — the rules block the backend
// merges into /map/manifest (backend/_01_map/api_service._rules_dto).
const RULES = {
  frame: [519.1, 20.9, 221.3, 217.3],
  zoom_max: 10.8,
  pan_margin_fraction: 0.0,
  label_min_width_px: 48,
  search_min_chars: 2,
  search_max_results: 20,
  colors: {
    neutral_province: '#8C8C8C',
    sea: '#1E3547',
    outside: '#2A2A2A',
    inland_water: '#1E3547',
    province_border: '#3A3A3A',
    land_underlay: '#8C8C8C',
    hover: '#FFFFFF',
  },
  hover_fill_opacity: 0.14,
  hover_stroke_enabled: false,
  borders: {
    internal_width: 0.8,
    internal_opacity: 0.45,
    internal_color: '#4A4A4A',
    state_width: 1.8,
    state_color: '#101014',
    coast_width: 0.9,
    coast_color: '#24262B',
  },
  selection: {
    pulse_min_opacity: 0.1,
    pulse_max_opacity: 0.32,
    pulse_period_s: 2.4,
    picked_opacity: 0.28,
  },
  require_connected_start: true,
  big_window_enabled: true,
  refresh: {
    tick_refresh_delay_seconds: 5,
    tick_refresh_jitter_seconds: 30,
    retry_delay_seconds: 10,
    max_retries: 3,
    stale_after_seconds: 900,
  },
};

async function loadJson(name) {
  return JSON.parse(await readFile(join(DATA, name), 'utf-8'));
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

function send(res, status, body, type = 'application/json; charset=utf-8') {
  const buf = Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  res.writeHead(status, {
    'Content-Type': type,
    'Content-Length': buf.length,
    'Cache-Control': 'no-store',
  });
  res.end(buf);
}

async function makeServer() {
  const manifestFile = await loadJson('manifest.json');
  const geometry = await loadJson('geometry.json');
  const borders = await loadJson('borders.json');
  const manifest = {
    ...manifestFile,
    rules: RULES,
    attribution: 'Карта: MapChart.net, лицензия CC BY-SA 4.0',
  };
  const mapState = {
    geometry_version: manifest.geometry_version,
    borders_version: manifest.borders_version,
    turn: 1,
    nations: [],
    owners: [],
  };
  const api = (url) => {
    const p = url.pathname;
    if (p === '/api/v1/auth/vk' && url.method === 'POST') {
      return {
        access_token: 'perf-token',
        token_type: 'bearer',
        expires_in: 3600,
        player: {
          id: '00000000-0000-4000-8000-000000000001',
          vk_user_id: 1,
          created_at: '2026-01-01T00:00:00Z',
        },
      };
    }
    if (p === '/api/v1/map/manifest') return manifest;
    if (p.startsWith('/api/v1/map/geometry/')) return geometry;
    if (p.startsWith('/api/v1/map/borders/')) return borders;
    if (p === '/api/v1/map/state') return mapState;
    if (p === '/api/v1/nations/rules') {
      return {
        name_min_length: 2,
        name_max_length: 40,
        leader_name_min_length: 2,
        leader_name_max_length: 40,
        leader_title_min_length: 2,
        leader_title_max_length: 40,
        history_url_max_length: 200,
        history_url_allowed_hosts: ['ru.wikipedia.org'],
        min_provinces: 1,
        max_provinces: 9,
      };
    }
    if (p === '/api/v1/bot/status') {
      return {
        enabled: false,
        consent: 'UNKNOWN',
        stale: false,
        throttled: false,
        registration_requires_consent: false,
        chat_url: null,
        consent_poll_interval_seconds: null,
        consent_poll_timeout_seconds: null,
      };
    }
    if (p === '/api/v1/game-clock') {
      return {
        current_turn: 1,
        game_date: '1400-01-01',
        next_tick_at: '2026-01-02T00:00:00Z',
      };
    }
    if (p === '/api/v1/provinces') return [];
    return null;
  };

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? '/', 'http://bench');
      url.method = req.method;
      if (url.pathname.startsWith('/api/v1/')) {
        const body = api(url);
        if (body !== null) {
          return send(res, 200, body);
        }
        if (url.pathname === '/api/v1/nations/me') {
          return send(res, 404, {
            code: 'NATION_NOT_FOUND',
            detail: 'no nation',
          });
        }
        if (url.pathname === '/api/v1/admin/me') {
          return send(res, 403, {
            code: 'ADMIN_REQUIRED',
            detail: 'not an admin',
          });
        }
        return send(res, 404, { code: 'NOT_FOUND', detail: 'stub' });
      }
      const rel =
        url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const file = join(DIST, rel);
      if (!resolve(file).startsWith(DIST)) {
        return send(res, 403, 'forbidden', 'text/plain');
      }
      try {
        const body = await readFile(file);
        return send(res, 200, body, MIME[extname(file)] ?? 'application/octet-stream');
      } catch {
        // SPA fallback — the hash router lives in index.html.
        const body = await readFile(join(DIST, 'index.html'));
        return send(res, 200, body, MIME['.html']);
      }
    } catch (error) {
      return send(res, 500, { error: String(error) });
    }
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  return server;
}

/* --------------------------------------------- playwright resolve */

async function loadPlaywright() {
  const req = createRequire(import.meta.url);
  const candidates = [
    process.env.PLAYWRIGHT_MODULE,
    'playwright',
    join(
      execSync('npm root -g').toString().trim(),
      'playwright',
    ),
  ].filter(Boolean);
  for (const c of candidates) {
    try {
      return req(c);
    } catch {
      /* try next */
    }
  }
  throw new Error(
    'playwright package not found — `npm i -g playwright` or set PLAYWRIGHT_MODULE',
  );
}

/* --------------------------------------------------- in-page bits */

const RECORDER = () => {
  const rec = { on: false, ts: [] };
  const loop = (t) => {
    if (!rec.on) {
      return;
    }
    rec.ts.push(t);
    requestAnimationFrame(loop);
  };
  window.__pgRec = {
    start() {
      rec.ts = [];
      rec.on = true;
      requestAnimationFrame(loop);
    },
    stop() {
      rec.on = false;
      const ts = rec.ts.slice();
      const d = [];
      for (let i = 1; i < ts.length; i += 1) {
        d.push(ts[i] - ts[i - 1]);
      }
      return d;
    },
  };
};

const APPLY_VARIANT = (variant) => {
  const v = variant.split(',');
  const hide = (sel) =>
    document
      .querySelectorAll(sel)
      .forEach((el) => (el.style.display = 'none'));
  if (v.includes('no-borders') || v.includes('all-off')) {
    hide('[data-layer="borders"]');
  }
  if (v.includes('no-internal')) {
    hide('[data-border="internal"]');
  }
  if (v.includes('no-labels')) {
    hide('[data-layer="labels"]');
  }
  if (v.includes('no-seam')) {
    // map2_14: the seam cover is the land-coloured stroke on the
    // nodes <g>, inherited by every fill — zero the group width
    // (diagnostic only, leaves cracks between provinces).
    document
      .querySelector('g[data-layer="nodes"]')
      ?.setAttribute('stroke-width', '0');
  }
  if (v.includes('no-nss')) {
    const world = document.querySelector('[data-testid="map-view"] svg > g');
    const m = /scale\(([\d.eE+-]+)\)/.exec(
      world?.getAttribute('transform') ?? '',
    );
    const s = m ? parseFloat(m[1]) : 1;
    // map2_14: the stroke style lives on the [data-border] groups,
    // vector-effect on the chunk paths inside them.
    document.querySelectorAll('[data-border]').forEach((g) => {
      const w = parseFloat(g.getAttribute('stroke-width') ?? '1');
      g.querySelectorAll('path').forEach((p) => {
        p.removeAttribute('vector-effect');
        p.setAttribute('stroke-width', String(w / s));
      });
      if (g.tagName.toLowerCase() === 'path') {
        g.removeAttribute('vector-effect');
        g.setAttribute('stroke-width', String(w / s));
      }
    });
  }
  if (v.includes('no-pulse') || v.includes('all-off')) {
    const style = document.createElement('style');
    style.textContent = '.pg-map-selected-pulse{animation:none!important}';
    document.head.appendChild(style);
  }
};

// Click the centre of a land node so the selection overlay (pulse) is
// active for all measurements; returns the clicked id or null.
const SELECT_NODE = () => {
  const world = document.querySelector('svg > g');
  const paths = [...document.querySelectorAll('path[data-id]')];
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  for (const p of paths) {
    const r = p.getBoundingClientRect();
    if (
      r.width > 20 &&
      r.height > 20 &&
      r.left > vw * 0.2 &&
      r.right < vw * 0.8 &&
      r.top > vh * 0.2 &&
      r.bottom < vh * 0.8
    ) {
      const cx = (r.left + r.right) / 2;
      const cy = (r.top + r.bottom) / 2;
      return { x: cx, y: cy, id: Number(p.getAttribute('data-id')) };
    }
  }
  return null;
};

/* -------------------------------------------------------- gestures */

async function recordDuring(page, fn) {
  await page.evaluate(() => window.__pgRec.start());
  await fn();
  await page.waitForTimeout(250); // settle tail (final React commit)
  return page.evaluate(() => window.__pgRec.stop());
}

async function wheelZoom(page, cx, cy, notches) {
  await page.mouse.move(cx, cy);
  return recordDuring(page, async () => {
    for (let i = 0; i < notches; i += 1) {
      await page.mouse.wheel(0, -120);
      await page.waitForTimeout(80);
    }
  });
}

async function drag(page, cx, cy) {
  const legs = [
    { dx: 420, dy: 240, steps: 30 },
    { dx: -420, dy: -240, steps: 30 },
  ];
  return recordDuring(page, async () => {
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    let x = cx;
    let y = cy;
    for (const leg of legs) {
      for (let i = 1; i <= leg.steps; i += 1) {
        await page.mouse.move(
          x + (leg.dx * i) / leg.steps,
          y + (leg.dy * i) / leg.steps,
        );
        await page.waitForTimeout(30);
      }
      x += leg.dx;
      y += leg.dy;
    }
    await page.mouse.up();
  });
}

/* ----------------------------------------------------------- stats */

function stats(deltas) {
  const sorted = deltas.slice().sort((a, b) => a - b);
  const pick = (q) =>
    sorted.length === 0
      ? 0
      : sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
  return {
    n: sorted.length,
    median: pick(0.5),
    p95: pick(0.95),
    over33: sorted.filter((d) => d > 33).length,
  };
}

const fmt = (s) =>
  `n=${s.n} median=${s.median.toFixed(1)}ms p95=${s.p95.toFixed(1)}ms over33=${s.over33}`;

/* ------------------------------------------------------------ main */

async function main() {
  const playwright = await loadPlaywright();
  const server = await makeServer();
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}`;

  let browser = null;
  for (const channel of ['chrome', 'msedge', undefined]) {
    try {
      browser = await playwright.chromium.launch({
        channel,
        headless: !HEADED,
      });
      console.error(`browser: ${channel ?? 'bundled'}`);
      break;
    } catch {
      /* next channel */
    }
  }
  if (!browser) {
    throw new Error('no chromium channel could launch');
  }

  const all = {}; // scenario -> {pan:[], zoom:[]}
  const NOTCHES = { out: 1, med: 4, high: 5 }; // cumulative z: 1.25, 3.05, 9.31

  for (let run = 0; run < RUNS; run += 1) {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 900 },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    if (THROTTLE > 1) {
      const cdp = await context.newCDPSession(page);
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: THROTTLE });
    }
    await page.goto(`${base}/#/map`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('path[data-id]', { timeout: 60000 });
    await page.evaluate(RECORDER);
    await page.waitForTimeout(1200); // first paint, fonts, React settle

    // Select a land node — the selection overlay is part of real usage.
    const target = await page.evaluate(SELECT_NODE);
    if (target) {
      await page.mouse.click(target.x, target.y);
      await page.waitForTimeout(600);
    }
    await page.evaluate(APPLY_VARIANT, VARIANT);
    await page.waitForTimeout(300);

    const cx = 800;
    const cy = 450;
    for (const [name, notches] of Object.entries(NOTCHES)) {
      const z = await wheelZoom(page, cx, cy, notches);
      await page.waitForTimeout(400);
      const p = await drag(page, cx, cy);
      await page.waitForTimeout(400);
      (all[name] ??= { pan: [], zoom: [] }).pan.push(...p);
      all[name].zoom.push(...z);
    }
    await context.close();
  }

  await browser.close();
  server.close();

  console.log(`build=${TAG} variant=${VARIANT} throttle=${THROTTLE}x runs=${RUNS}`);
  for (const [name, s] of Object.entries(all)) {
    console.log(`scenario ${name} pan: ${fmt(stats(s.pan))}`);
    console.log(`scenario ${name} zoom: ${fmt(stats(s.zoom))}`);
  }
  if (JSON_OUT) {
    const { writeFile } = await import('node:fs/promises');
    await writeFile(JSON_OUT, JSON.stringify({ tag: TAG, variant: VARIANT, all }, null, 2));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
