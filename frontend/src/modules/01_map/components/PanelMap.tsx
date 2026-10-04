/**
 * PanelMap — the map screen (Spec Part 5 «Клиентские компоненты»,
 * «Вход на экран карты»).
 *
 * Top row: search field, the big-window button, «Назад» (hidden in
 * fullscreen). Centre: MapView filling the remaining space, NodeCard
 * floating right. Bottom: status line «Ход N · обновлено ЧЧ:ММ»
 * (Moscow time) with «данные устарели» when 3.10 says so, the colour
 * legend and the attribution string.
 *
 * The screen is position:fixed — it covers the app viewport in normal
 * view and the whole monitor once the page goes fullscreen, regardless
 * of how VKUI lays out the surrounding panels.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouteNavigator } from '@vkontakte/vk-mini-apps-router';
import {
  Button,
  FormStatus,
  ScreenSpinner,
  Search,
  Text,
} from '@vkontakte/vkui';

import { buildAdjacency } from '../lib/adjacency';
import { buildOwnerMap } from '../lib/colors';
import { formatMoscowTime } from '../lib/refresh';
import { displayName } from '../lib/search';
import type { MapNodeDTO } from '../types';
import { useBigWindow } from '../hooks/useBigWindow';
import { useMapGeometry } from '../hooks/useMapGeometry';
import { useMapManifest } from '../hooks/useMapManifest';
import { useMapSearch } from '../hooks/useMapSearch';
import { useMapState } from '../hooks/useMapState';
import { MapView, type MapViewFocus } from './MapView';
import { NodeCard } from './NodeCard';

const LEGEND: { key: string; label: string }[] = [
  { key: 'neutral_province', label: 'Свободная провинция' },
  { key: 'sea', label: 'Морская зона' },
  { key: 'inland_water', label: 'Озёра' },
  { key: 'outside', label: 'За краем игрового поля' },
];

export function PanelMap() {
  const navigator = useRouteNavigator();
  const manifestState = useMapManifest();
  const manifest =
    manifestState.status === 'ready' ? manifestState.manifest : null;
  const geometryState = useMapGeometry(
    manifest?.geometry_version ?? null,
    manifestState.reload,
  );
  const mapState = useMapState(manifest?.rules.refresh ?? null);
  const { query, setQuery, results } = useMapSearch(manifest);
  const bigWindow = useBigWindow();

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [focus, setFocus] = useState<MapViewFocus | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const focusSeq = useRef(0);

  const nodesById = useMemo(
    () => new Map((manifest?.nodes ?? []).map((n) => [n.id, n])),
    [manifest],
  );
  const adjacency = useMemo(
    () => buildAdjacency(manifest?.edges ?? []),
    [manifest],
  );
  const owners = useMemo(
    () => buildOwnerMap(mapState.state, nodesById),
    [mapState.state, nodesById],
  );

  const selectedNode =
    selectedId !== null ? (nodesById.get(selectedId) ?? null) : null;
  const neighbours = useMemo(
    () =>
      selectedNode === null
        ? []
        : (adjacency.get(selectedNode.id) ?? [])
            .map((ref) => ({
              node: nodesById.get(ref.nodeId),
              edge: ref.edge,
            }))
            .filter(
              (r): r is { node: MapNodeDTO; edge: typeof r.edge } =>
                r.node !== undefined,
            ),
    [selectedNode, adjacency, nodesById],
  );

  const requestFocus = (mode: MapViewFocus['mode'], node: MapNodeDTO) => {
    focusSeq.current += 1;
    setFocus({ seq: focusSeq.current, mode, bbox: node.bbox });
  };

  const pickNode = (node: MapNodeDTO, mode: MapViewFocus['mode']) => {
    setSelectedId(node.id);
    requestFocus(mode, node);
  };

  // Esc: the open card closes first; a still-open search list goes before.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') {
        return;
      }
      if (searchOpen) {
        setSearchOpen(false);
      } else if (selectedId !== null) {
        setSelectedId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [searchOpen, selectedId]);

  const chooseResult = (node: MapNodeDTO) => {
    pickNode(node, 'fit');
    setSearchOpen(false);
    setActiveIndex(-1);
  };

  const onSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const delta = e.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((i) =>
        Math.min(results.length - 1, Math.max(0, i + delta)),
      );
    } else if (e.key === 'Enter') {
      const node = results[activeIndex >= 0 ? activeIndex : 0];
      if (node) {
        chooseResult(node);
      }
    } else if (e.key === 'Escape') {
      setSearchOpen(false);
    }
  };

  /* -------------------------------------------------------- status line */

  const statusParts: string[] = [];
  if (mapState.state) {
    statusParts.push(`Ход ${mapState.state.turn}`);
    statusParts.push(
      `обновлено ${formatMoscowTime(mapState.fetchedAt ?? Date.now())}`,
    );
  } else if (mapState.status === 'error') {
    statusParts.push('не удалось загрузить данные карты');
  } else {
    statusParts.push('данные загружаются…');
  }
  if (mapState.stale) {
    statusParts.push('данные устарели');
  }

  const colors = manifest?.rules.colors;

  /* ------------------------------------------------------------ render */

  const bigWindowVisible =
    bigWindow.supported && manifest?.rules.big_window_enabled === true;

  return (
    <div
      data-testid="panel-map"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 10,
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--vkui--color_background)',
      }}
    >
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          padding: '8px 12px',
        }}
      >
        <div style={{ position: 'relative', flex: 1, maxWidth: 420 }}>
          <Search
            value={query}
            placeholder="Найти провинцию или морскую зону"
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchOpen(true);
              setActiveIndex(-1);
            }}
            onKeyDown={onSearchKeyDown}
            onFocus={() => setSearchOpen(true)}
          />
          {searchOpen && results.length > 0 && (
            <div
              data-testid="map-search-results"
              role="listbox"
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                zIndex: 20,
                background: 'var(--vkui--color_background_content)',
                border: '1px solid var(--vkui--color_separator_primary)',
                borderRadius: 8,
                maxHeight: 320,
                overflowY: 'auto',
              }}
            >
              {results.map((node, i) => (
                <button
                  key={node.id}
                  type="button"
                  role="option"
                  aria-selected={i === activeIndex}
                  data-result-id={node.id}
                  onClick={() => chooseResult(node)}
                  style={{
                    display: 'block',
                    width: '100%',
                    textAlign: 'left',
                    padding: '8px 12px',
                    border: 0,
                    background:
                      i === activeIndex
                        ? 'var(--vkui--color_background_secondary)'
                        : 'transparent',
                    cursor: 'pointer',
                  }}
                >
                  {displayName(node)}
                  <Text
                    style={{ opacity: 0.6, marginLeft: 8 }}
                    Component="span"
                  >
                    {node.kind === 'SEA' ? 'морская зона' : 'провинция'}
                  </Text>
                </button>
              ))}
            </div>
          )}
        </div>

        {bigWindowVisible && (
          <Button
            mode="primary"
            onClick={bigWindow.isFullscreen ? bigWindow.exit : bigWindow.enter}
          >
            {bigWindow.isFullscreen
              ? 'Свернуть'
              : 'Развернуть на весь экран'}
          </Button>
        )}
        {!bigWindow.isFullscreen && (
          <Button mode="secondary" onClick={() => navigator.push('/')}>
            Назад
          </Button>
        )}
      </div>

      {bigWindow.error && (
        <FormStatus mode="error">{bigWindow.error}</FormStatus>
      )}

      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        {manifestState.status === 'error' && (
          <div style={{ padding: 24 }}>
            <FormStatus mode="error" title="Не удалось загрузить карту">
              {manifestState.error.message}
            </FormStatus>
            <Button
              size="l"
              style={{ marginTop: 12 }}
              onClick={() => void manifestState.reload()}
            >
              Повторить
            </Button>
          </div>
        )}
        {manifestState.status !== 'error' &&
          geometryState.status === 'error' && (
            <div style={{ padding: 24 }}>
              <FormStatus mode="error" title="Не удалось загрузить геометрию">
                {geometryState.error.message}
              </FormStatus>
              <Button
                size="l"
                style={{ marginTop: 12 }}
                onClick={geometryState.retry}
              >
                Повторить
              </Button>
            </div>
          )}
        {manifest === null || geometryState.geometry === null ? (
          manifestState.status !== 'error' &&
          geometryState.status !== 'error' && <ScreenSpinner />
        ) : (
          <MapView
            mode="view"
            manifest={manifest}
            geometry={geometryState.geometry}
            state={mapState.state}
            selectedIds={selectedId === null ? [] : [selectedId]}
            onNodeClick={(id) => setSelectedId(id)}
            focus={focus}
          />
        )}
        {selectedNode && (
          <NodeCard
            node={selectedNode}
            owner={
              selectedNode.kind === 'LAND'
                ? (owners.get(selectedNode.id) ?? null)
                : null
            }
            neighbours={neighbours}
            onNeighbourClick={(id) => {
              const node = nodesById.get(id);
              if (node) {
                pickNode(node, 'center');
              }
            }}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>

      <div
        data-testid="map-status"
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'center',
          flexWrap: 'wrap',
          padding: '6px 12px',
          fontSize: 13,
        }}
      >
        <span>{statusParts.join(' · ')}</span>
        {colors &&
          // «Озёра» is shown only while lakes differ from the sea
          // (normalised HEX, case-insensitive) — equal colours would
          // describe one colour twice.
          LEGEND.filter(
            (item) =>
              item.key !== 'inland_water' ||
              colors.inland_water.toUpperCase() !==
                colors.sea.toUpperCase(),
          ).map((item) => (
            <span
              key={item.key}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
            >
              <span
                style={{
                  display: 'inline-block',
                  width: 12,
                  height: 12,
                  borderRadius: 3,
                  background: colors[item.key],
                }}
              />
              {item.label}
            </span>
          ))}
        <span style={{ marginLeft: 'auto', opacity: 0.6 }}>
          {manifest?.attribution}
        </span>
      </div>
    </div>
  );
}
