/**
 * Name search — Spec 3.12, pure functions.
 *
 * Normalisation: casefold (toLowerCase), ё→е, trim and collapse runs of
 * whitespace. Match is a substring over `name_ru` and `name`. Results:
 * names starting with the query first, then the rest; inside each group
 * by ascending display-name length; capped at `search_max_results`;
 * queries shorter than `search_min_chars` are not processed.
 */

import type { MapNodeDTO } from '../types';

export function normalizeQuery(value: string): string {
  return value
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Display name of a node: `name_ru` when set, else `name` (Spec Part 1). */
export function displayName(node: MapNodeDTO): string {
  return node.name_ru ?? node.name;
}

export interface SearchLimits {
  minChars: number;
  maxResults: number;
}

export function searchNodes(
  nodes: MapNodeDTO[],
  query: string,
  limits: SearchLimits,
): MapNodeDTO[] {
  const needle = normalizeQuery(query);
  if (needle.length < limits.minChars) {
    return [];
  }

  const startsWith: MapNodeDTO[] = [];
  const contains: MapNodeDTO[] = [];
  for (const node of nodes) {
    const names = [normalizeQuery(displayName(node))];
    if (node.name_ru !== null) {
      names.push(normalizeQuery(node.name));
    }
    if (!names.some((n) => n.includes(needle))) {
      continue;
    }
    if (names.some((n) => n.startsWith(needle))) {
      startsWith.push(node);
    } else {
      contains.push(node);
    }
  }

  const byLength = (a: MapNodeDTO, b: MapNodeDTO) =>
    displayName(a).length - displayName(b).length || a.id - b.id;
  startsWith.sort(byLength);
  contains.sort(byLength);

  return startsWith.concat(contains).slice(0, limits.maxResults);
}
