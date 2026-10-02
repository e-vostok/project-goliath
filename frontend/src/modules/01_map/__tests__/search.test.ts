/**
 * Search (Spec 3.12): normalisation (ё→е, casefold, spaces), substring
 * over name_ru and name, prefix-first ordering, ascending name length,
 * result cap, minimum query length.
 */

import { displayName, normalizeQuery, searchNodes } from '../lib/search';
import type { MapNodeDTO } from '../types';

const node = (
  id: number,
  name: string,
  name_ru: string | null = null,
): MapNodeDTO => ({
  id,
  key: `n${id}`,
  kind: 'LAND',
  name,
  name_ru,
  anchor: [0, 0],
  bbox: [0, 0, 1, 1],
  area: 1,
});

const LIMITS = { minChars: 2, maxResults: 3 };

const NODES = [
  node(1, 'Moscow', 'Москва'),
  node(2, 'Mosquito Bay', 'Москитная бухта'),
  node(3, 'Novomoskovsk', 'Новомосковск'),
  node(4, 'Yolka', 'Ёлка'),
  node(5, 'Amos', null),
  node(6, 'Scania', 'Скания'),
];

describe('normalizeQuery', () => {
  it.each([
    ['  МоСКВА  ', 'москва'],
    ['Ёлка', 'елка'],
    ['a   b\t c', 'a b c'],
    ['ЁЖ ёж', 'еж еж'],
  ])('normalises %j → %j', (input, expected) => {
    expect(normalizeQuery(input)).toBe(expected);
  });
});

describe('displayName', () => {
  it('prefers name_ru, falls back to name', () => {
    expect(displayName(node(1, 'X', 'Икс'))).toBe('Икс');
    expect(displayName(node(2, 'X'))).toBe('X');
  });
});

describe('searchNodes', () => {
  it('matches case-insensitively on name_ru', () => {
    const hits = searchNodes(NODES, 'МОСКВА', LIMITS);
    expect(hits.map((n) => n.id)).toEqual([1]);
  });

  it('ё и е are interchangeable in the query', () => {
    expect(searchNodes(NODES, 'елка', LIMITS).map((n) => n.id)).toEqual([4]);
    expect(searchNodes(NODES, 'ЁЛКА', LIMITS).map((n) => n.id)).toEqual([4]);
  });

  it('collapses whitespace and trims', () => {
    const hits = searchNodes(NODES, '  москитная   бухта ', LIMITS);
    expect(hits.map((n) => n.id)).toEqual([2]);
  });

  it('puts names starting with the query first', () => {
    // 'мос' (cyrillic): Москва + Москитная бухта are prefix hits,
    // Новомосковск contains it mid-word; latin 'Amos' does not match.
    const hits = searchNodes(NODES, 'мос', { minChars: 2, maxResults: 10 });
    const prefixIds = hits
      .slice(0, 2)
      .map((n) => n.id)
      .sort();
    expect(prefixIds).toEqual([1, 2]);
    expect(hits.slice(2).map((n) => n.id)).toEqual([3]); // contains group
  });

  it('orders inside a group by ascending display-name length', () => {
    const hits = searchNodes(NODES, 'мос', { minChars: 2, maxResults: 10 });
    // prefix group: 'Москва' (6) then 'Москитная бухта' (15)
    expect(hits[0].id).toBe(1);
    expect(hits[1].id).toBe(2);
  });

  it('respects the result cap', () => {
    // 'ск' hits Скания (prefix), Москва, Москитная бухта, Новомосковск
    const hits = searchNodes(NODES, 'ск', LIMITS); // maxResults = 3
    expect(hits).toHaveLength(3);
    expect(hits[0].id).toBe(6); // prefix group first
  });

  it('ignores queries below the minimum length', () => {
    expect(searchNodes(NODES, 'м', LIMITS)).toEqual([]);
    expect(searchNodes(NODES, '   ', LIMITS)).toEqual([]);
  });

  it('matches on the latin name when name_ru is shown', () => {
    // 'moscow' is the latin name of node 1 (shown as Москва).
    const hits = searchNodes(NODES, 'moscow', LIMITS);
    expect(hits.map((n) => n.id)).toEqual([1]);
  });
});
