/**
 * map_pan_visual.mjs — VISUAL correctness benchmark for the 01_map
 * screen (map2_14). Complements map_pan.mjs, which measures speed:
 * this script measures whether a frame in the middle of a drag shows
 * the real, complete map or a stale/frozen approximation.
 *
 * Method (per build, per zoom scenario):
 *   - A scripted slow 400 px drag is driven through Playwright at
 *     1920×1080 on the REAL map. The drag is cut into 5 segments; at
 *     each boundary a screenshot is taken WHILE the mouse button is
 *     still held (mid-gesture), then the button is released and, after
 *     the map has settled, a REFERENCE screenshot of the very same view
 *     position is taken (settled = ground truth of what the player is
 *     supposed to see at that position).
 *   - A final screenshot is taken ~60 ms after the LAST button release
 *     ("gesture just ended") plus one fully settled shot at the end.
 *   - For every mid-gesture shot the script reports the share of
 *     pixels that differ noticeably from its settled reference, the
 *     share of edge-band pixels showing the page background where the
 *     reference does not (blank/stale strips), and the same diff for
 *     the "just ended" shot vs the last mid-gesture shot (a jump).
 *   - A MutationObserver counts, only while the button is held:
 *     childList rebuilds anywhere under the world <g>, `d` rewrites on
 *     any path, and display toggles on layer groups. Target for a pure
 *     drag: 0.
 *
 * Usage:
 *   node tools/perf/map_pan_visual.mjs --dist frontend/dist [--tag main]
 *     [--scenarios out,med] [--headed] [--json out.json]
 *
 * Same stub server and Playwright resolution as map_pan.mjs — the
 * duplication is deliberate (perf tools are standalone scripts).
 */

import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
const SCENARIOS = opt('scenarios', 'out,med').split(',');
const HEADED = args.includes('--headed');
const JSON_OUT = opt('json', null);

const VIEW_W = 1920;
const VIEW_H = 1080;
/** Total drag travel, px, and the slow-drag pace. Diagonal: the x
 *  axis is centre-locked at low zoom, so a pure horizontal drag would
 *  move nothing there. */
const DRAG_DX = 400;
const DRAG_DY = 240;
const STEPS = 40;
const STEP_MS = 50;
/** Segment boundaries (step counts) where screenshots are taken. */
const MOMENTS = [16, 20, 24, 28, 32];
/** Wheel notches per scenario (×1.25 each from z = 1). */
const NOTCHES = { out: 1, med: 5 };
/** Per-channel diff above this counts as a noticeable difference. */
const DIFF_LEVEL = 24;
/** Edge band scanned for blank/background strips, px. */
const EDGE_PX = 24;

/* ------------------------------------------------- API stub data */

// Identical to map_pan.mjs: the rules block the backend merges into
// /map/manifest, from configs/01_map.yaml.
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

const OUTSIDE_RGB = [0x2a, 0x2a, 0x2a];
const SEA_RGB = [0x1e, 0x35, 0x47];

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
      const rel = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      const file = join(DIST, rel);
      if (!resolve(file).startsWith(DIST)) {
        return send(res, 403, 'forbidden', 'text/plain');
      }
      try {
        const body = await readFile(file);
        return send(
          res,
          200,
          body,
          MIME[extname(file)] ?? 'application/octet-stream',
        );
      } catch {
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
    join(execSync('npm root -g').toString().trim(), 'playwright'),
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

// Mutation accounting: `rebuilds` counts childList changes under the
// world <g> plus `d` rewrites on any path (chunk/border rebakes);
// `layerToggles` counts display/visibility flips on layer groups.
const OBSERVER = () => {
  const acc = { rebuilds: 0, layerToggles: 0, armed: false };
  const world = document.querySelector('[data-testid="map-view"] svg > g');
  if (!world) {
    window.__pgMut = acc;
    return;
  }
  const mo = new MutationObserver((muts) => {
    if (!acc.armed) {
      return;
    }
    for (const m of muts) {
      if (m.type === 'childList') {
        acc.rebuilds += 1;
      } else if (m.type === 'attributes') {
        if (m.attributeName === 'd') {
          acc.rebuilds += 1;
        } else if (
          m.attributeName !== 'transform' &&
          m.target instanceof SVGGElement
        ) {
          // Anything that is neither geometry nor the world transform:
          // display flips, style deltas (labels hidden, svg moved) —
          // all count as layer toggles.
          acc.layerToggles += 1;
        }
      }
    }
  });
  mo.observe(world, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['d', 'display', 'style'],
  });
  window.__pgMut = acc;
};

// Decode two PNG buffers (base64) and diff them: share of pixels whose
// max channel difference exceeds `level`, and — inside the edge band —
// the share of pixels that sit on the page background colour while the
// reference does not (blank/stale strips).
const DIFF = async ([aB64, bB64, level, edge, bg]) => {
  const decode = async (b64) => {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) {
      bytes[i] = bin.charCodeAt(i);
    }
    const bmp = await createImageBitmap(new Blob([bytes]));
    const cv = document.createElement('canvas');
    cv.width = bmp.width;
    cv.height = bmp.height;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(bmp, 0, 0);
    return ctx.getImageData(0, 0, cv.width, cv.height);
  };
  const [A, B] = await Promise.all([decode(aB64), decode(bB64)]);
  const n = A.width * A.height;
  let differ = 0;
  let edgeTotal = 0;
  let edgeBlank = 0;
  const isBg = (d, i) =>
    bg.some(
      ([r, g, b]) =>
        Math.abs(d[i] - r) <= 6 &&
        Math.abs(d[i + 1] - g) <= 6 &&
        Math.abs(d[i + 2] - b) <= 6,
    );
  for (let p = 0; p < n; p += 1) {
    const i = p * 4;
    const x = p % A.width;
    const y = (p / A.width) | 0;
    const dA = Math.max(
      Math.abs(A.data[i] - B.data[i]),
      Math.abs(A.data[i + 1] - B.data[i + 1]),
      Math.abs(A.data[i + 2] - B.data[i + 2]),
    );
    if (dA > level) {
      differ += 1;
    }
    if (
      x < edge ||
      x >= A.width - edge ||
      y < edge ||
      y >= A.height - edge
    ) {
      edgeTotal += 1;
      if (isBg(A.data, i) && !isBg(B.data, i)) {
        edgeBlank += 1;
      }
    }
  }
  return {
    diff: differ / n,
    edgeBlank: edgeTotal === 0 ? 0 : edgeBlank / edgeTotal,
  };
};

/* -------------------------------------------------------- gestures */

async function settle(page, ms = 700) {
  await page.waitForTimeout(ms);
}

async function shot(page) {
  const buf = await page.screenshot({ type: 'png' });
  return buf.toString('base64');
}

// One scenario on one page: drag in 5 segments; at each boundary take
// a mid-gesture shot, release, settle, take the reference shot.
async function runScenario(page, name) {
  const cx = VIEW_W / 2;
  const cy = VIEW_H / 2;
  const notches = NOTCHES[name] ?? 0;
  await page.mouse.move(cx, cy);
  for (let i = 0; i < notches; i += 1) {
    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(90);
  }
  await settle(page);

  const out = { mid: {}, ref: {}, jump: {}, mutations: {} };
  let step = 0;
  for (const k of MOMENTS) {
    // Count mutations only while the button is held — a pure drag must
    // rebuild nothing; the settle window after release may legitimately
    // re-evaluate the label set (Spec 3.9).
    await page.evaluate(() => {
      window.__pgMut.rebuilds = 0;
      window.__pgMut.layerToggles = 0;
      window.__pgMut.armed = true;
    });
    await page.mouse.down();
    for (; step < k; step += 1) {
      await page.mouse.move(
        cx + (DRAG_DX * (step + 1)) / STEPS,
        cy + (DRAG_DY * (step + 1)) / STEPS,
      );
      await page.waitForTimeout(STEP_MS);
    }
    // One extra beat so the last transform lands before the shot.
    await page.waitForTimeout(STEP_MS);
    out.mid[k] = await shot(page);
    const mut = await page.evaluate(() => {
      window.__pgMut.armed = false;
      return {
        rebuilds: window.__pgMut.rebuilds,
        layerToggles: window.__pgMut.layerToggles,
      };
    });
    out.mutations[k] = mut;
    await page.mouse.up();
    if (k === MOMENTS[MOMENTS.length - 1]) {
      // "Gesture just ended" — before any settle work can run.
      await page.waitForTimeout(60);
      out.jump.shot = await shot(page);
    }
    await settle(page);
    out.ref[k] = await shot(page);
  }
  return out;
}

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

  const context = await browser.newContext({
    viewport: { width: VIEW_W, height: VIEW_H },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await page.goto(`${base}/#/map`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('path[data-id]', { timeout: 60000 });
  await page.evaluate(OBSERVER);
  try {
    // Builds without the border layer (v0.5.8) simply time out here.
    await page.waitForSelector('[data-layer="borders"]', {
      timeout: 5000,
    });
  } catch {
    /* older build */
  }
  await page.waitForTimeout(1200); // first paint, fonts, React settle

  const report = {};
  for (const name of SCENARIOS) {
    const run = await runScenario(page, name);
    const diffs = [];
    const edges = [];
    for (const k of MOMENTS) {
      const r = await page.evaluate(DIFF, [
        run.mid[k],
        run.ref[k],
        DIFF_LEVEL,
        EDGE_PX,
        [OUTSIDE_RGB, SEA_RGB],
      ]);
      diffs.push(r.diff);
      edges.push(r.edgeBlank);
    }
    // Jump: shot right after the last release vs its mid-gesture twin,
    // and the settled end state vs the same mid-gesture shot.
    const lastK = MOMENTS[MOMENTS.length - 1];
    const jumpNow = await page.evaluate(DIFF, [
      run.jump.shot,
      run.mid[lastK],
      DIFF_LEVEL,
      EDGE_PX,
      [OUTSIDE_RGB, SEA_RGB],
    ]);
    const jumpSettled = await page.evaluate(DIFF, [
      run.ref[lastK],
      run.mid[lastK],
      DIFF_LEVEL,
      EDGE_PX,
      [OUTSIDE_RGB, SEA_RGB],
    ]);
    const maxRebuilds = Math.max(
      ...MOMENTS.map((k) => run.mutations[k].rebuilds),
    );
    const maxToggles = Math.max(
      ...MOMENTS.map((k) => run.mutations[k].layerToggles),
    );
    report[name] = {
      diffShare: diffs.map((d) => Number(d.toFixed(4))),
      edgeBlankShare: edges.map((d) => Number(d.toFixed(4))),
      jumpEnd: Number(jumpNow.diff.toFixed(4)),
      jumpSettled: Number(jumpSettled.diff.toFixed(4)),
      rebuilds: maxRebuilds,
      layerToggles: maxToggles,
    };
    console.log(
      `scenario ${name}: diff%=${diffs.map((d) => (d * 100).toFixed(2)).join(',')} ` +
        `edgeBlank%=${edges.map((d) => (d * 100).toFixed(2)).join(',')} ` +
        `jumpEnd=${(jumpNow.diff * 100).toFixed(2)}% jumpSettled=${(jumpSettled.diff * 100).toFixed(2)}% ` +
        `rebuilds=${maxRebuilds} toggles=${maxToggles}`,
    );
    // Back to z = 1 for the next scenario.
    await page.mouse.move(VIEW_W / 2, VIEW_H / 2);
    for (let i = 0; i < (NOTCHES[name] ?? 0); i += 1) {
      await page.mouse.wheel(0, 120);
      await page.waitForTimeout(90);
    }
    await settle(page);
  }

  await browser.close();
  server.close();

  console.log(`build=${TAG}`);
  if (JSON_OUT) {
    const { writeFile } = await import('node:fs/promises');
    await writeFile(JSON_OUT, JSON.stringify({ tag: TAG, report }, null, 2));
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
