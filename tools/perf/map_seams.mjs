/**
 * map_seams.mjs — sea-pixel check along internal province borders (map2_13).
 *
 * Bug: between neighbouring land provinces of the same owner (or both
 * free) a hairline of the SEA colour shows through — anti-aliasing on
 * fills that do not overlap exactly. The script serves a BUILT client
 * (vite build output) with the same tiny /api/v1/* stub as
 * map_pan.mjs — the rules block is parsed from configs/01_map.yaml so
 * the same script measures before- and after-fix builds — injects a
 * red nation around Constantinople/Gallipoli (the pair «Гелиболу» —
 * «Стамбул» becomes internal to a state; «Сиврихисар» stays free),
 * zooms headless Chromium to the Marmara/Anatolia area, screenshots
 * 1920×1080 and counts SEA-coloured pixels sampled along every
 * internal border polyline inside the visible rect (the shared edges
 * of borders.json), plus a sea-side sanity: pixels along coast
 * polylines, pixels at the anchors of the visible SEA nodes and the
 * total sea-pixel count must stay sea — coasts and straits must not
 * be covered by the fix.
 *
 * Usage:
 *   node tools/perf/map_seams.mjs --dist frontend/dist [--tag main]
 *     [--json out.json] [--png shot.png] [--headed] [--notches 7]
 *
 * Requires playwright (see map_pan.mjs) and Chrome/Edge/bundled build.
 * A SCRIPT REPORT, not a permanent test (TZ map2_13).
 */

import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), '../..');
const DATA = join(ROOT, 'data', 'map');
const CONFIG = join(ROOT, 'configs', '01_map.yaml');

/* ------------------------------------------------------------ args */

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
}
const DIST = resolve(opt('dist', 'frontend/dist'));
const TAG = opt('tag', DIST);
const JSON_OUT = opt('json', null);
const PNG_OUT = opt('png', null);
const HEADED = args.includes('--headed');
const NOTCHES = Number(opt('notches', '7')); // ×1.25 each — med/high zoom
// World point the viewport centres on: between Стамбул (656,180) and
// Сиврихисар (667,187) — the two seam examples of the bug report.
const CENTRE = [656.5, 184.5];

/* ------------------------------------------- configs/01_map.yaml */

// Minimal reader for this config's shape: each top-level `section:`
// holds flat `key: value` lines (comments stripped, scalars coerced);
// only `view.frame` nests one level and is handled by its own regex.
// The wire `rules` block is then composed like
// backend/_01_map/api_service._rules_dto.
async function loadRules() {
  const text = (await readFile(CONFIG, 'utf-8')).replace(/\r\n?/g, '\n');
  const frameBlock = /view:[\s\S]*?frame:[^\n]*\n\s+x:\s*([\d.]+)[^\n]*\n\s+y:\s*([\d.]+)[^\n]*\n\s+width:\s*([\d.]+)[^\n]*\n\s+height:\s*([\d.]+)/.exec(text);
  if (!frameBlock) {
    throw new Error('view.frame block not found in 01_map.yaml');
  }
  const [, fx, fy, fw, fh] = frameBlock.map(Number);
  const sec = (name) => {
    const m = new RegExp(`^${name}:\\s*\\n((?:[ \\t]+[^\\n]*\\n)+)`, 'm').exec(text);
    if (!m) return {};
    const out = {};
    for (const l of m[1].split('\n')) {
      const kv = /^\s+([A-Za-z_][\w]*):\s*(.*?)\s*$/.exec(l.replace(/\s+#.*$/, ''));
      if (kv && kv[2] !== '') {
        let v = kv[2].replace(/^['"]|['"]$/g, '');
        if (v === 'true') v = true;
        else if (v === 'false') v = false;
        else if (!Number.isNaN(Number(v))) v = Number(v);
        out[kv[1]] = v;
      }
    }
    return out;
  };
  const colors = sec('colors');
  const refresh = sec('refresh');
  const hover = sec('hover');
  const borders = sec('borders');
  const selection = sec('selection');
  const bigWindow = sec('big_window');
  const view = sec('view');
  const starting = sec('starting_group');
  return {
    frame: [fx, fy, fw, fh],
    zoom_max: view.zoom_max,
    pan_margin_fraction: view.pan_margin_fraction,
    label_min_width_px: view.label_min_width_px,
    search_min_chars: view.search_min_chars,
    search_max_results: view.search_max_results,
    colors,
    hover_fill_opacity: hover.fill_opacity,
    hover_stroke_enabled: hover.stroke_enabled,
    borders,
    selection,
    require_connected_start: starting.require_connected,
    big_window_enabled: bigWindow.enabled,
    refresh: {
      tick_refresh_delay_seconds: refresh.tick_refresh_delay_seconds,
      tick_refresh_jitter_seconds: refresh.tick_refresh_jitter_seconds,
      retry_delay_seconds: refresh.retry_delay_seconds,
      max_retries: refresh.max_retries,
      stale_after_seconds: refresh.stale_after_seconds,
    },
  };
}

/* ------------------------------------------------- API stub data */

// Red nation around Constantinople–Gallipoli: pair 1211-1236 becomes
// an INTERNAL border inside a strong state colour, while Сиврихисар
// (1822) and all its neighbours stay free. Region rule mirrors the
// owners list injected into /map/state below.
const NATION_REGION = { x0: 642, x1: 663, y0: 174, y1: 189 };
const NATION_COLOR = '#E04545';

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

function nationIds(manifest) {
  return manifest.nodes
    .filter(
      (n) =>
        n.kind === 'LAND' &&
        n.anchor[0] >= NATION_REGION.x0 &&
        n.anchor[0] <= NATION_REGION.x1 &&
        n.anchor[1] >= NATION_REGION.y0 &&
        n.anchor[1] <= NATION_REGION.y1,
    )
    .map((n) => n.id);
}

async function makeServer(rules, manifestFile, geometry, borders, state) {
  const manifest = {
    ...manifestFile,
    rules,
    attribution: 'Карта: MapChart.net, лицензия CC BY-SA 4.0',
  };
  const api = (url) => {
    const p = url.pathname;
    if (p === '/api/v1/auth/vk' && url.method === 'POST') {
      return {
        access_token: 'seam-token',
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
    if (p === '/api/v1/map/state') return state;
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
          return send(res, 404, { code: 'NATION_NOT_FOUND', detail: 'no nation' });
        }
        if (url.pathname === '/api/v1/admin/me') {
          return send(res, 403, { code: 'ADMIN_REQUIRED', detail: 'not an admin' });
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
        return send(res, 200, body, MIME[extname(file)] ?? 'application/octet-stream');
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

// The whole sampling: shot → canvas → per-polyline sea-pixel count.
// `view` is the baked world transform read from the <g> attribute.
// Everything runs in-page — helpers live inside the function.
const SAMPLE = async ({ b64, view, payload, seaRgb, tol }) => {
  // Parses a path like "M x y x y …" (multiple M allowed) into
  // polylines of [x,y]; the borders file holds open straight segments.
  const PATH_TO_LINES = (d) => {
    const tokens =
      d.match(/[MmLlZz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/g) ?? [];
    const lines = [];
    let cur = null;
    for (let i = 0; i < tokens.length; i += 1) {
      const t = tokens[i];
      if (t === 'M' || t === 'm') {
        cur = [[parseFloat(tokens[i + 1]), parseFloat(tokens[i + 2])]];
        lines.push(cur);
        i += 2;
      } else if (t === 'L' || t === 'l') {
        cur?.push([parseFloat(tokens[i + 1]), parseFloat(tokens[i + 2])]);
        i += 1;
      } else if (t === 'Z' || t === 'z') {
        if (cur && cur.length > 0) cur.push(cur[0]);
        cur = null;
      } else {
        // bare pair: after M the first pair is the moveto; further
        // pairs are implicit lineto
        cur?.push([parseFloat(t), parseFloat(tokens[i + 1])]);
        i += 1;
      }
    }
    return lines.filter((l) => l.length > 1);
  };
  const img = new Image();
  await new Promise((res, rej) => {
    img.onload = res;
    img.onerror = rej;
    img.src = 'data:image/png;base64,' + b64;
  });
  const canvas = document.createElement('canvas');
  canvas.width = img.width;
  canvas.height = img.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  const W = canvas.width;
  const H = canvas.height;

  const toScreen = (p) => [view.tx + view.s * p[0], view.ty + view.s * p[1]];
  const isSea = (x, y) => {
    const xi = Math.round(x);
    const yi = Math.round(y);
    if (xi < 0 || yi < 0 || xi >= W || yi >= H) return null; // off shot
    const i = (yi * W + xi) * 4;
    const dr = data[i] - seaRgb[0];
    const dg = data[i + 1] - seaRgb[1];
    const db = data[i + 2] - seaRgb[2];
    return dr * dr + dg * dg + db * db <= tol * tol;
  };
  // Sea-LEANING pixel: blue-dominant and within blend distance of the
  // sea colour. The bug's signature on fills is mostly anti-aliased
  // blends (fill×sea) that stay blue-dominant — pure sea within `tol`
  // appears only in the widest part of a crack. Land fills, the grey
  // underlay and the grey borders are never blue-dominant, so they
  // cannot register.
  const isSeaT = (x, y) => {
    const xi = Math.round(x);
    const yi = Math.round(y);
    if (xi < 0 || yi < 0 || xi >= W || yi >= H) return null; // off shot
    const i = (yi * W + xi) * 4;
    if (data[i + 2] - data[i] < 15) return false;
    const dr = data[i] - seaRgb[0];
    const dg = data[i + 1] - seaRgb[1];
    const db = data[i + 2] - seaRgb[2];
    return dr * dr + dg * dg + db * db <= 90 * 90;
  };

  // Walk each segment in ~1.25 px screen steps; at every step probe a
  // 3-pixel cross-section (−0.9, 0, +0.9 px perpendicular) — a seam
  // hairline sits up to ~1 px beside the canonical line. For every sea
  // pixel found, the sea-run width along the same perpendicular tells
  // a hairline (≤3 px of sea before land resumes) from a real water
  // body (a longer run — channels, lakes, inlets). World coords and
  // the run width are kept so Node can finish the classification.
  const seaRun = (x, y, dx, dy) => {
    let w = 1;
    for (const s of [1, -1]) {
      for (let d = 1; d <= 8; d += 1) {
        if (isSeaT(x + dx * s * d, y + dy * s * d) !== true) break;
        w += 1;
      }
    }
    return w;
  };
  // Width of the water feature at the pixel: the WORST sea run over the
  // perpendicular and its two diagonals. A hairline crack keeps all
  // three short; a shoreline pixel touches open water on at least one
  // diagonal (run grows long) — the pair border meeting the coast is
  // not the bug.
  const seaWidth = (x, y, dx, dy) => {
    const d45 = Math.SQRT1_2;
    const dx1 = dx * d45 - dy * d45;
    const dy1 = dx * d45 + dy * d45;
    const dx2 = dx * d45 + dy * d45;
    const dy2 = -dx * d45 + dy * d45;
    return Math.max(
      seaRun(x, y, dx, dy),
      seaRun(x, y, dx1, dy1),
      seaRun(x, y, dx2, dy2),
    );
  };
  const alongPath = (d) => {
    let sea = 0;
    let n = 0;
    const seaPts = [];
    for (const line of PATH_TO_LINES(d)) {
      for (let s = 0; s < line.length - 1; s += 1) {
        const a = toScreen(line[s]);
        const b = toScreen(line[s + 1]);
        const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (len === 0) continue;
        const ux = (b[0] - a[0]) / len;
        const uy = (b[1] - a[1]) / len;
        const px = -uy;
        const py = ux;
        const steps = Math.max(1, Math.ceil(len / 1.25));
        for (let k = 0; k <= steps; k += 1) {
          const cx = a[0] + ux * ((len * k) / steps);
          const cy = a[1] + uy * ((len * k) / steps);
          for (const off of [-0.9, 0, 0.9]) {
            const r = isSeaT(cx + px * off, cy + py * off);
            if (r === null) continue;
            n += 1;
            if (r) {
              sea += 1;
              seaPts.push({
                p: [
                  (cx + px * off - view.tx) / view.s,
                  (cy + py * off - view.ty) / view.s,
                ],
                w: seaWidth(cx + px * off, cy + py * off, px, py),
              });
            }
          }
        }
      }
    }
    return { sea, n, seaPts };
  };

  const out = { pairs: {}, coastSea: 0, coastN: 0, anchors: [], totalSea: 0 };
  for (const [key, d] of Object.entries(payload.pairs)) {
    out.pairs[key] = alongPath(d);
  }
  for (const d of Object.values(payload.coasts)) {
    const r = alongPath(d);
    out.coastSea += r.sea;
    out.coastN += r.n;
  }
  for (const p of payload.seaAnchors) {
    const s = toScreen(p);
    // The label text sits on the anchor — probe a 6 px ring around it.
    let sea = false;
    for (let dx = -6; dx <= 6 && !sea; dx += 2) {
      for (let dy = -6; dy <= 6 && !sea; dy += 2) {
        sea = isSea(s[0] + dx, s[1] + dy) === true;
      }
    }
    out.anchors.push({ at: p, sea });
  }
  for (let i = 0; i < W * H * 4; i += 4) {
    const dr = data[i] - seaRgb[0];
    const dg = data[i + 1] - seaRgb[1];
    const db = data[i + 2] - seaRgb[2];
    if (dr * dr + dg * dg + db * db <= tol * tol) out.totalSea += 1;
  }
  return out;
};

const READ_VIEW = () => {
  const g = document.querySelector('[data-testid="map-view"] svg > g');
  const m = g?.getScreenCTM(); // world → client px, svg offset included
  return m ? { tx: m.e, ty: m.f, s: m.a } : { tx: 0, ty: 0, s: 0 };
};

/* ----------------------------------- land coverage (Node side) */

// A sea pixel is a SEAM leak only when its world point lies on land
// territory (a fill covers it within AA fringe). Sea pixels sitting
// in real voids — lakes, channels, sea nodes, coastal inlets — are
// legitimate water, not the bug. Port of the gap-check geometry walk.
const TOKRE = /[MLZmlz]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/g;
function parseRings(d) {
  const toks = d.match(TOKRE) ?? [];
  const out = [];
  let cur = null;
  for (let i = 0; i < toks.length; i += 1) {
    const t = toks[i];
    if (t === 'M' || t === 'm') {
      if (cur) out.push(cur);
      cur = [[parseFloat(toks[i + 1]), parseFloat(toks[i + 2])]];
      i += 2;
    } else if (t === 'Z' || t === 'z') {
      if (cur) {
        cur.push(cur[0]);
        out.push(cur);
      }
      cur = null;
    } else if (t === 'L' || t === 'l') {
      cur?.push([parseFloat(toks[i + 1]), parseFloat(toks[i + 2])]);
      i += 1;
    } else {
      cur?.push([parseFloat(t), parseFloat(toks[i + 1])]);
      i += 1;
    }
  }
  if (cur) {
    cur.push(cur[0]);
    out.push(cur);
  }
  return out;
}

function pointInRing(p, ring) {
  let inside = false;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[i + 1];
    if (y1 > p[1] !== y2 > p[1]) {
      if (x1 + ((p[1] - y1) * (x2 - x1)) / (y2 - y1) > p[0]) inside = !inside;
    }
  }
  return inside;
}

function segDist(p, a, b) {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const L2 = dx * dx + dy * dy;
  if (L2 === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

const LAND_EPS = 0.02; // AA-fringe radius in map units
function buildLandIndex(manifestFile, geometry) {
  const land = [];
  for (const n of manifestFile.nodes) {
    if (n.kind !== 'LAND') continue;
    const rings = parseRings(geometry.paths[String(n.id)] ?? '');
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const r of rings) {
      for (const [x, y] of r) {
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x > x1) x1 = x;
        if (y > y1) y1 = y;
      }
    }
    land.push({ rings, x0: x0 - LAND_EPS, y0: y0 - LAND_EPS, x1: x1 + LAND_EPS, y1: y1 + LAND_EPS });
  }
  return land;
}
// SEA nodes plus the sea_water overlay (bays): pixels covered by these
// are real water — a sea-coloured pixel there is never the seam bug,
// even when a land polygon's fringe overlaps it at a coast.
function buildSeaIndex(manifestFile, geometry) {
  const sea = buildLandIndex(
    { nodes: manifestFile.nodes.filter((n) => n.kind === 'SEA') },
    geometry,
  );
  for (const rings of [parseRings(geometry.sea_water ?? '')]) {
    if (rings.length === 0) continue;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const r of rings) {
      for (const [x, y] of r) {
        if (x < x0) x0 = x;
        if (y < y0) y0 = y;
        if (x > x1) x1 = x;
        if (y > y1) y1 = y;
      }
    }
    sea.push({ rings, x0: x0 - LAND_EPS, y0: y0 - LAND_EPS, x1: x1 + LAND_EPS, y1: y1 + LAND_EPS });
  }
  return sea;
}
function distToLand(land, p) {
  let dmin = Infinity;
  for (const node of land) {
    if (p[0] < node.x0 || p[0] > node.x1 || p[1] < node.y0 || p[1] > node.y1) continue;
    for (const ring of node.rings) {
      if (pointInRing(p, ring)) return 0;
      for (let i = 0; i < ring.length - 1; i += 1) {
        const d = segDist(p, ring[i], ring[i + 1]);
        if (d < dmin) dmin = d;
      }
    }
  }
  return dmin;
}

/* ------------------------------------------------------------ main */

async function main() {
  const playwright = await loadPlaywright();
  const rules = await loadRules();
  const manifestFile = await loadJson('manifest.json');
  const geometry = await loadJson('geometry.json');
  const borders = await loadJson('borders.json');

  const owned = new Set(nationIds(manifestFile));
  const state = {
    geometry_version: manifestFile.geometry_version,
    borders_version: manifestFile.borders_version,
    turn: 1,
    nations: [
      { id: null, name: 'Рубрикон', color_hex: NATION_COLOR },
    ],
    owners: [...owned].map((id) => [id, 0]),
  };
  // Same classification the client applies (borders.ts): same owner or
  // both free → internal, different → state.
  const classify = (key) => {
    const [a, b] = key.split('-').map(Number);
    return (owned.has(a) ? 1 : 0) === (owned.has(b) ? 1 : 0)
      ? 'internal'
      : 'state';
  };

  const server = await makeServer(rules, manifestFile, geometry, borders, state);
  const port = server.address().port;

  let browser = null;
  for (const channel of ['chrome', 'msedge', undefined]) {
    try {
      browser = await playwright.chromium.launch({ channel, headless: !HEADED });
      console.error(`browser: ${channel ?? 'bundled'}`);
      break;
    } catch {
      /* next channel */
    }
  }
  if (!browser) throw new Error('no chromium channel could launch');

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:${port}/#/map`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('path[data-id]', { timeout: 60000 });
  await page.waitForTimeout(1500); // paint, fonts, React settle
  if (process.env.SEAMS_DEBUG) {
    console.error('rules.frame', JSON.stringify(rules.frame), 'zoom_max', rules.zoom_max);
    console.error(
      'dom view',
      JSON.stringify(
        await page.evaluate(() => ({
          attr: document
            .querySelector('[data-testid="map-view"] svg > g')
            ?.getAttribute('transform'),
          ctm: (() => {
            const m = document
              .querySelector('[data-testid="map-view"] svg > g')
              ?.getScreenCTM();
            return m ? { a: m.a, e: m.e, f: m.f } : null;
          })(),
        })),
      ),
    );
  }

  // Centre the Marmara point, then wheel-zoom into it (zoomAt keeps
  // the world point under the cursor — a real gesture path).
  let view = await page.evaluate(READ_VIEW);
  const c0 = [
    view.tx + view.s * CENTRE[0],
    view.ty + view.s * CENTRE[1],
  ];
  await page.mouse.move(c0[0], c0[1]);
  for (let i = 0; i < NOTCHES; i += 1) {
    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(120);
  }
  await page.waitForTimeout(600); // settle → baked transform
  view = await page.evaluate(READ_VIEW);
  const c1 = [view.tx + view.s * CENTRE[0], view.ty + view.s * CENTRE[1]];
  await page.mouse.move(c1[0], c1[1]);
  await page.mouse.down();
  await page.mouse.move(960, 540, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(700);
  view = await page.evaluate(READ_VIEW);

  // Visible world rect — pairs/coasts outside it are skipped (their
  // samples would all be off-canvas anyway; the filter keeps the
  // report readable and selects exactly the checked region).
  const wv = {
    x0: (0 - view.tx) / view.s,
    y0: (0 - view.ty) / view.s,
    x1: (1920 - view.tx) / view.s,
    y1: (1080 - view.ty) / view.s,
  };
  const mid = (d) => {
    const nums = d.match(/[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/g).map(Number);
    let sx = 0;
    let sy = 0;
    let n = 0;
    for (let i = 0; i + 1 < nums.length; i += 2) {
      sx += nums[i];
      sy += nums[i + 1];
      n += 1;
    }
    return n ? [sx / n, sy / n] : null;
  };
  const inRect = (p) =>
    p && p[0] >= wv.x0 && p[0] <= wv.x1 && p[1] >= wv.y0 && p[1] <= wv.y1;

  const pairs = {};
  for (const [key, d] of Object.entries(borders.pairs)) {
    if (classify(key) === 'internal' && inRect(mid(d))) {
      pairs[key] = d;
    }
  }
  // The two reported examples must be in the checked set.
  const must = ['1211-1236'];
  for (const [key, d] of Object.entries(borders.pairs)) {
    if (key.split('-').map(Number).includes(1822)) must.push(key);
  }
  for (const key of must) {
    if (borders.pairs[key] && classify(key) === 'internal') {
      pairs[key] = borders.pairs[key];
    }
  }
  const nodeById = new Map(manifestFile.nodes.map((n) => [n.id, n]));
  const coasts = {};
  for (const [idStr, d] of Object.entries(borders.coasts)) {
    const n = nodeById.get(Number(idStr));
    if (n && inRect(n.anchor)) coasts[idStr] = d;
  }
  const seaAnchors = manifestFile.nodes
    .filter((n) => n.kind === 'SEA' && inRect(n.anchor))
    .map((n) => n.anchor);

  const shot = await page.screenshot({ type: 'png' });
  if (PNG_OUT) await writeFile(PNG_OUT, shot);
  const seaRgb = rules.colors.sea
    .replace('#', '')
    .match(/../g)
    .map((h) => parseInt(h, 16));
  const report = await page.evaluate(SAMPLE, {
    b64: shot.toString('base64'),
    view,
    payload: { pairs, coasts, seaAnchors },
    seaRgb,
    tol: 16,
  });

  await context.close();
  await browser.close();
  server.close();

  // ---------- console report
  // Classify every sea pixel. A SEAM leak must (a) sit on land
  // territory, (b) be clear of every modelled water body (SEA node /
  // sea_water — pixels under those fills, incl. the coastal AA fringe,
  // are legitimate water), and (c) be a HAIRLINE — a sea run of at
  // most HAIRLINE_PX screen pixels perpendicular to the border. A
  // longer run means an unmodelled water channel between provinces
  // (e.g. the Euboea channel): real water drawn by the inland-water
  // rect, not the bug.
  const HAIRLINE_PX = 3;
  const land = buildLandIndex(manifestFile, geometry);
  const seaIdx = buildSeaIndex(manifestFile, geometry);
  let seamPx = 0;
  let waterPx = 0;
  let nPx = 0;
  const perPair = {};
  for (const [key, r] of Object.entries(report.pairs)) {
    let seam = 0;
    let water = 0;
    for (const pt of r.seaPts) {
      if (
        pt.w <= HAIRLINE_PX &&
        distToLand(land, pt.p) <= LAND_EPS &&
        distToLand(seaIdx, pt.p) > LAND_EPS
      ) seam += 1;
      else water += 1;
    }
    seamPx += seam;
    waterPx += water;
    nPx += r.n;
    perPair[key] = {
      seam,
      water,
      n: r.n,
      seamPts: r.seaPts
        .filter(
          (pt) =>
            pt.w <= HAIRLINE_PX &&
            distToLand(land, pt.p) <= LAND_EPS &&
            distToLand(seaIdx, pt.p) > LAND_EPS,
        )
        .map((pt) => pt.p.map((v) => Math.round(v * 100) / 100)),
    };
  }
  const entries = Object.entries(perPair).sort(
    (a, b) => b[1].seam - a[1].seam,
  );
  console.log(`build=${TAG} centre=${CENTRE} scale=${view.s.toFixed(2)}`);
  console.log(
    `internal pairs checked: ${entries.length}  samples: ${nPx}`,
  );
  console.log(
    `sea-leaning px on land territory (the seam bug): ${seamPx}`,
  );
  console.log(`sea-leaning px on real water (lakes/channels, must stay): ${waterPx}`);
  for (const [key, r] of entries.slice(0, 15)) {
    if (r.seam === 0) break;
    console.log(`  ${key}: seam=${r.seam} water=${r.water} n=${r.n}`);
  }
  console.log(
    `coast polylines: ${Object.keys(coasts).length}  ` +
      `SEA px along coasts: ${report.coastSea}/${report.coastN}`,
  );
  console.log(
    `sea anchors in view: ${report.anchors.length}  sea-coloured: ` +
      report.anchors.filter((a) => a.sea).length,
  );
  console.log(`total SEA px in shot: ${report.totalSea}`);

  if (JSON_OUT) {
    await writeFile(
      JSON_OUT,
      JSON.stringify(
        {
          tag: TAG,
          view,
          centre: CENTRE,
          nation: [...owned],
          pairsInternal: entries.length,
          seamPx,
          waterPx,
          samplePx: nPx,
          perPair,
          coastSea: report.coastSea,
          coastN: report.coastN,
          anchors: report.anchors,
          totalSea: report.totalSea,
        },
        null,
        2,
      ),
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
