/**
 * useMapSearch — query state + Spec 3.12 search over manifest nodes.
 * The matching itself is the pure lib/search.searchNodes.
 */

import { useMemo, useState } from 'react';

import { searchNodes } from '../lib/search';
import type { MapManifestDTO, MapNodeDTO } from '../types';

export interface MapSearch {
  query: string;
  setQuery: (value: string) => void;
  results: MapNodeDTO[];
}

export function useMapSearch(manifest: MapManifestDTO | null): MapSearch {
  const [query, setQuery] = useState('');

  const results = useMemo(() => {
    if (manifest === null) {
      return [];
    }
    return searchNodes(manifest.nodes, query, {
      minChars: manifest.rules.search_min_chars,
      maxResults: manifest.rules.search_max_results,
    });
  }, [manifest, query]);

  return { query, setQuery, results };
}
