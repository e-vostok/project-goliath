/**
 * parseStartHash — the `register` start hint from the bot keyboard
 * (Spec 5.5/5.6): exact match after one leading '#'; everything else —
 * including `map` — stays untouched for the owning module.
 */

import { normalizeEntryHash } from '../../../app/AppShell';
import { parseStartHash } from '../lib/startHash';

describe('parseStartHash', () => {
  it.each([
    ['#register', 'register'],
    ['register', 'register'],
    ['#map', null],
    ['#', null],
    ['', null],
    ['#register&x=1', null],
    ['#register?x=1', null],
    ['#REGISTER', null],
    ['#unknown', null],
    ['##register', null],
  ])('%s → %s', (hash, expected) => {
    expect(parseStartHash(hash)).toBe(expected);
  });
});

describe('normalizeEntryHash — register hint', () => {
  afterEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('maps #register to the registration route', () => {
    window.location.hash = '#register';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/nation/new');
  });

  it('still maps #map to the map route (01_map owns it)', () => {
    window.location.hash = '#map';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#/map');
  });

  it('leaves unrelated hashes untouched', () => {
    window.location.hash = '#something-else';
    normalizeEntryHash();
    expect(window.location.hash).toBe('#something-else');
  });
});
