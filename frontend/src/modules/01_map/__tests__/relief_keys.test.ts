/**
 * map2_16 retired the map2_5 dimming/fade config keys
 * (`inactive_tint`, `inactive_opacity`, `edge_fade_units`,
 * `margin_units`). This test fails if any code path in the map
 * module or the module config reintroduces one — grep-based, so it
 * also catches stray fixture data and dead branches.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const RETIRED = [
  'inactive_tint',
  'inactive_opacity',
  'edge_fade_units',
  'margin_units',
];

const ROOTS = [
  resolve(__dirname, '..'), // the whole 01_map module source
  resolve(__dirname, '../../../../../configs/01_map.yaml'),
];

function* sources(dir: string): Generator<string> {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      yield* sources(path);
    } else if (/\.(tsx?|json|ya?ml)$/.test(entry)) {
      yield path;
    }
  }
}

describe('map2_16 — retired relief keys are gone', () => {
  it('no module source or the map config mentions them', () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
      const files = statSync(root).isDirectory()
        ? [...sources(root)]
        : [root];
      for (const file of files) {
        // The test file itself names the keys on purpose.
        if (file.endsWith('relief_keys.test.ts')) continue;
        const text = readFileSync(file, 'utf8');
        for (const key of RETIRED) {
          if (text.includes(key)) {
            offenders.push(`${key} @ ${file}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
