/**
 * PanelRegistry — the «Реестр» window (Spec 5.5, UI Spec 9.2).
 *
 * An ordinary block in the page flow (the VK window follows the
 * content height — nothing here is pinned to it): screen title
 * («РЕЕСТР», shared BlockTitle without the filling line — the signed
 * text tabs «Игроки / Государства / …» sit in the same row, UI Spec
 * 9.2 mockup «Registry») → toolbar (search, «Показано N из M»,
 * «Фильтры», «Обновить», «Сбросить») → the in-flow filter panel
 * (toggled by «Фильтры», normal document flow across the window
 * width) → table block (`surface`, `radius-lg`, max-height 720 px;
 * overflow-x:hidden, overflow-y:auto, sticky header — the 910 px
 * window rule: no horizontal scrollbar, Spec 5.5). With
 * layout.tabs_position = right the tabs become a vertical icon column
 * to the right of the table block. The screen is as tall as its
 * content. Navigation lives in the shared top bar — no own «Назад».
 *
 * Sort, filters, search and the filter-panel toggle of each tab live
 * in this component's state and survive tab switches; leaving the
 * panel resets them (Bible 2.7 — VKUI View keeps panels mounted, so
 * the reset is done explicitly on the `active` prop flipping to
 * false, not by unmount).
 *
 * The entry request (Spec 5.5 «Вход с предустановкой») selects a tab
 * and may carry a `preset` — the filters the tab opens with — and/or
 * a cell `action`. Requests arrive two ways: the `entryRequest` prop
 * (the `#registry/order-N` hash path) and the shared store
 * (in-app `setRegistryEntryRequest`, taken on activation and heard
 * through `onRegistryEntryRequest`). Registered table filter
 * extensions add their «Все / Да» controls to the filter panel;
 * their number sets load lazily on the first «Да» and on «Обновить».
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, FormStatus, Spinner } from '@vkontakte/vkui';

import { errorText } from '../../../shared/errorTexts';
import { BlockTitle, RADII, SPACING, tokenVar } from '../../../shared/ui';

import { useSession } from '../../00_core/hooks/useAuth';
import { useNationOptions, NATIONS_TABLE_ID } from '../hooks/useNationOptions';
import { useRegistryRows } from '../hooks/useRegistryRows';
import { useRegistryTables } from '../hooks/useRegistryTables';
import { runCellAction } from '../lib/cellActions';
import { nationNamesOfRows } from '../lib/nationOptions';
import {
  onRegistryEntryRequest,
  takeRegistryEntryRequest,
  type RegistryEntryRequest,
} from '../lib/entryRequest';
import {
  getTableFilterExtensions,
  type ExtensionSetState,
  type TableFilterExtension,
} from '../lib/tableFilterExtensions';
import {
  applyEntryPreset,
  applyView,
  EMPTY_VIEW,
  hasActiveFilters,
  isFilterActive,
  nextSort,
  type TableView,
} from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import { FilterPanel } from './FilterPanel';
import { RegistryTable } from './RegistryTable';
import { TableToolbar } from './TableToolbar';
import { TabStrip } from './TabStrip';

export function PanelRegistry({
  entryRequest = null,
  active = true,
  onOpenNation,
  onOpenPlayer,
}: {
  /**
   * Deep-link request from AppShell (Spec 04_orders 5.5): select `tab`
   * if it exists and, once its rows are loaded, run `action` exactly
   * like a click on an `action_text` cell would.
   */
  entryRequest?: RegistryEntryRequest | null;
  /**
   * Whether this screen is the visible one — AppShell feeds it the
   * active panel. Going false is «the panel was left»: the per-tab
   * view state resets (Bible 2.7).
   */
  active?: boolean;
  /**
   * A nation cell click opens the nation subscreen (unit 14c); the
   * second argument is the active tab's title for the return path
   * chain («Реестр / <tab> / <название>»).
   */
  onOpenNation?: (nationId: string, fromTabTitle: string) => void;
  /**
   * A person cell click opens the «Игрок» subscreen (0.10.0 unit
   * 8b); the arguments are the player's public Registry number (the
   * row key `p<N>`) and the active tab's title for the path chain.
   */
  onOpenPlayer?: (playerNumber: number, fromTabTitle: string) => void;
}) {
  const { token } = useSession();
  const tablesState = useRegistryTables();
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [views, setViews] = useState<Record<string, TableView>>({});
  const [pendingRequest, setPendingRequest] =
    useState<RegistryEntryRequest | null>(entryRequest);
  // Loaded number sets of the table filter extensions, by extension
  // id (Spec 5.5). Absent = never requested — an extension fetches
  // lazily, only when its control is switched to «Да».
  const [extStates, setExtStates] = useState<
    Record<string, ExtensionSetState>
  >({});

  const tables = tablesState.data?.tables ?? [];
  const tabsPosition = tablesState.data?.layout.tabs_position ?? 'top';
  const activeTableId = selectedTab ?? tables[0]?.id ?? null;
  const activeTable = tables.find((t) => t.id === activeTableId) ?? null;

  const rows = useRegistryRows(activeTableId);

  // The select_or_contains dropdowns list every nation the Registry
  // knows — the «nations» table; while it is absent/unloaded the
  // nations visible in the shown rows stand in (Spec 3.7).
  const needsNationOptions =
    activeTable?.columns.some((c) =>
      c.filters.includes('select_or_contains'),
    ) ?? false;
  const nationOptions = useNationOptions(
    needsNationOptions,
    tables.find((t) => t.id === NATIONS_TABLE_ID) ?? null,
  );
  const nationSelectOptions =
    nationOptions.names ?? nationNamesOfRows(rows.data);

  // Select the requested tab once the table list is known; a request
  // for a table that does not exist is dropped — the panel opens the
  // first tab as usual.
  useEffect(() => {
    if (!pendingRequest || tablesState.status !== 'ready') {
      return;
    }
    if (!tables.some((t) => t.id === pendingRequest.tab)) {
      setPendingRequest(null);
      return;
    }
    setSelectedTab(pendingRequest.tab);
  }, [pendingRequest, tablesState.status, tables]);

  // Once the requested tab is selected and its table description is
  // known, apply the preset to that tab's view state exactly once —
  // a field the player already changed in this visit keeps its value
  // (applyEntryPreset). A request carrying only a preset is spent here.
  useEffect(() => {
    if (!pendingRequest || activeTableId !== pendingRequest.tab) {
      return;
    }
    const table = tables.find((t) => t.id === pendingRequest.tab);
    if (!table || !pendingRequest.preset) {
      return;
    }
    const preset = pendingRequest.preset;
    const extensions = getTableFilterExtensions(table.id);
    setViews((prev) => ({
      ...prev,
      [table.id]: applyEntryPreset(
        prev[table.id] ?? EMPTY_VIEW,
        table,
        preset,
        extensions,
      ),
    }));
    setPendingRequest(
      pendingRequest.action
        ? { tab: pendingRequest.tab, action: pendingRequest.action }
        : null,
    );
  }, [pendingRequest, activeTableId, tables]);

  // A preset-only request has no action and was spent above; a request
  // without a preset and without action is spent here as well.
  useEffect(() => {
    if (
      pendingRequest &&
      !pendingRequest.action &&
      !pendingRequest.preset &&
      activeTableId === pendingRequest.tab
    ) {
      setPendingRequest(null);
    }
  }, [pendingRequest, activeTableId]);

  // Once the requested tab's rows are on screen, run the action — the
  // same call a cell click makes. `table_id` must match: on a tab
  // switch the hook still shows the previous table's rows for a beat.
  // A failed load leaves the request pending, so «Повторить» can run it.
  useEffect(() => {
    if (
      pendingRequest?.action &&
      activeTableId === pendingRequest.tab &&
      rows.data?.table_id === pendingRequest.tab
    ) {
      runCellAction(pendingRequest.action);
      setPendingRequest(null);
    }
  }, [pendingRequest, activeTableId, rows.data]);

  const view =
    (activeTableId ? views[activeTableId] : undefined) ?? EMPTY_VIEW;

  const updateView = (fn: (v: TableView) => TableView) => {
    if (!activeTableId) {
      return;
    }
    setViews((prev) => ({
      ...prev,
      [activeTableId]: fn(prev[activeTableId] ?? EMPTY_VIEW),
    }));
  };

  // The filter extensions registered for the open table (Spec 5.5) —
  // the Registry owns the control, the module owns the data.
  const activeExtensions = activeTable
    ? getTableFilterExtensions(activeTable.id)
    : [];

  const loadExtension = useCallback(
    (ext: TableFilterExtension) => {
      setExtStates((prev) =>
        prev[ext.id]?.status === 'loading'
          ? prev
          : { ...prev, [ext.id]: { status: 'loading' } },
      );
      ext.load(token).then(
        (set) =>
          setExtStates((prev) => ({
            ...prev,
            [ext.id]: { status: 'ready', set },
          })),
        (e: unknown) => {
          const error =
            e instanceof Error ? e : new Error('Неизвестная ошибка');
          setExtStates((prev) => ({
            ...prev,
            [ext.id]: { status: 'error', error },
          }));
          // A failed load leaves the filter off — the control shows
          // the usual error text and «Да» can be chosen again.
          setViews((prev) => {
            let changed = false;
            const out: Record<string, TableView> = {};
            for (const [tabId, v] of Object.entries(prev)) {
              if (v.extensions[ext.id] === 'yes') {
                out[tabId] = {
                  ...v,
                  extensions: { ...v.extensions, [ext.id]: 'any' },
                };
                changed = true;
              } else {
                out[tabId] = v;
              }
            }
            return changed ? out : prev;
          });
        },
      );
    },
    [token],
  );

  // Lazy load: an extension fetches its number set the first time its
  // control (or a preset) switches it to «Да» — never before.
  useEffect(() => {
    for (const ext of activeExtensions) {
      if (
        view.extensions[ext.id] === 'yes' &&
        extStates[ext.id] === undefined
      ) {
        loadExtension(ext);
      }
    }
  }, [activeExtensions, view.extensions, extStates, loadExtension]);

  const setExtensionValue = useCallback(
    (extId: string, value: 'any' | 'yes') => {
      const ext = activeExtensions.find((e) => e.id === extId);
      if (!ext) {
        return;
      }
      updateView((v) => ({
        ...v,
        extensions: { ...v.extensions, [extId]: value },
      }));
      // Retrying after a failed load: «Да» was turned back to «Все»
      // by the failure, so a fresh «Да» asks for the set again.
      if (value === 'yes' && extStates[extId]?.status === 'error') {
        loadExtension(ext);
      }
    },
    [activeExtensions, extStates, loadExtension],
  );

  // «Обновить» reloads the rows and every extension set in use.
  const refreshAll = useCallback(() => {
    rows.reload();
    for (const ext of activeExtensions) {
      if (view.extensions[ext.id] === 'yes') {
        loadExtension(ext);
      }
    }
  }, [rows, activeExtensions, view.extensions, loadExtension]);

  const readyExtSets = useMemo(() => {
    const out: Record<string, ReadonlySet<number>> = {};
    for (const [id, state] of Object.entries(extStates)) {
      if (state.status === 'ready') {
        out[id] = state.set;
      }
    }
    return out;
  }, [extStates]);

  const shownRows = useMemo(
    () =>
      activeTable && rows.data
        ? applyView(activeTable, rows.data.rows, view, readyExtSets)
        : [],
    [activeTable, rows.data, view, readyExtSets],
  );

  const activeFilterCount = useMemo(
    () =>
      Object.values(view.filters).reduce(
        (sum, list) => sum + list.filter(isFilterActive).length,
        0,
      ) +
      activeExtensions.filter((e) => view.extensions[e.id] === 'yes')
        .length,
    [view.filters, view.extensions, activeExtensions],
  );

  // In-app entries (the «Штаб» badges) call setRegistryEntryRequest
  // directly — no hash. On becoming active the panel takes any stored
  // request, and the subscription hears sets made while it is mounted.
  useEffect(() => {
    if (!active) {
      return;
    }
    const stored = takeRegistryEntryRequest();
    if (stored) {
      setPendingRequest(stored);
    }
    return onRegistryEntryRequest(setPendingRequest);
  }, [active]);

  // Leaving the screen is the old «Назад» reset — the panel stays
  // mounted inside VKUI View, so it is done explicitly when the
  // `active` flag drops (Bible 2.7).
  useEffect(() => {
    if (!active) {
      setViews({});
      setSelectedTab(null);
      setPendingRequest(null);
      setExtStates({});
    }
  }, [active]);

  const resetView = () =>
    updateView((v) => ({ ...v, search: '', filters: {}, extensions: {} }));

  /* -------------------------------------------------------- content */

  const content = (() => {
    if (tablesState.status === 'loading') {
      return (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            padding: '48px 0',
          }}
        >
          <Spinner size="l" />
        </div>
      );
    }
    if (tablesState.status === 'error') {
      return (
        <div style={{ padding: 24 }}>
          <FormStatus mode="error" title={REGISTRY_TEXTS.tablesLoadError}>
            {errorText(tablesState.error)}
          </FormStatus>
          <Button size="l" style={{ marginTop: 12 }} onClick={tablesState.reload}>
            {REGISTRY_TEXTS.retry}
          </Button>
        </div>
      );
    }
    if (!activeTable) {
      return null;
    }
    if (rows.status === 'loading' && !rows.data) {
      return (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            padding: '48px 0',
          }}
        >
          <Spinner size="l" />
        </div>
      );
    }
    if (!rows.data) {
      return (
        <div style={{ padding: 24 }}>
          <FormStatus mode="error" title={REGISTRY_TEXTS.rowsLoadError}>
            {errorText(rows.error)}
          </FormStatus>
          <Button size="l" style={{ marginTop: 12 }} onClick={rows.reload}>
            {REGISTRY_TEXTS.retry}
          </Button>
        </div>
      );
    }
    return (
      <>
        {rows.status === 'error' && (
          <div style={{ padding: '8px 12px' }}>
            <FormStatus mode="error" title={REGISTRY_TEXTS.rowsLoadError}>
              {errorText(rows.error)}
            </FormStatus>
            <Button
              size="s"
              style={{ marginTop: 8 }}
              onClick={rows.reload}
            >
              {REGISTRY_TEXTS.retry}
            </Button>
          </div>
        )}
        {shownRows.length > 0 ? (
          <RegistryTable
            table={activeTable}
            rows={shownRows}
            view={view}
            onSortClick={(columnId) =>
              updateView((v) => ({ ...v, sort: nextSort(v.sort, columnId) }))
            }
            onOpenNation={
              onOpenNation === undefined
                ? undefined
                : (nationId) => onOpenNation(nationId, activeTable.title)
            }
            onOpenPlayer={
              onOpenPlayer === undefined
                ? undefined
                : (playerNumber) =>
                    onOpenPlayer(playerNumber, activeTable.title)
            }
          />
        ) : rows.data.rows.length === 0 ? (
          <div style={{ padding: 24 }}>{activeTable.empty_text}</div>
        ) : (
          <div style={{ padding: 24 }}>
            <div>{REGISTRY_TEXTS.nothingFound}</div>
            <Button size="s" style={{ marginTop: 8 }} onClick={resetView}>
              {REGISTRY_TEXTS.reset}
            </Button>
          </div>
        )}
      </>
    );
  })();

  /* ------------------------------------------------------------ render */

  return (
    <div
      data-testid="panel-registry"
      style={{
        display: 'flex',
        flexDirection: 'column',
        padding: SPACING['space-4'],
        background: tokenVar('ground'),
      }}
    >
      <BlockTitle
        icon="list"
        title={REGISTRY_TEXTS.panelTitle}
        line={tabsPosition !== 'top' || tables.length === 0}
        trailing={
          tabsPosition === 'top' && tables.length > 0 ? (
            <TabStrip
              tables={tables}
              activeId={activeTableId}
              orientation="horizontal"
              onSelect={setSelectedTab}
            />
          ) : null
        }
      />

      {activeTable && (
        <TableToolbar
          search={view.search}
          onSearchChange={(search) => updateView((v) => ({ ...v, search }))}
          shown={rows.data ? shownRows.length : null}
          total={rows.data?.total ?? null}
          filtersOpen={view.filtersOpen}
          activeFilterCount={activeFilterCount}
          onToggleFilters={() =>
            updateView((v) => ({ ...v, filtersOpen: !v.filtersOpen }))
          }
          onRefresh={refreshAll}
          refreshing={rows.refreshing}
          onReset={resetView}
          resetDisabled={!hasActiveFilters(view)}
        />
      )}

      {activeTable && view.filtersOpen && (
        <FilterPanel
          table={activeTable}
          filters={view.filters}
          nationOptions={nationSelectOptions}
          extensions={activeExtensions}
          extensionValues={view.extensions}
          extensionStates={extStates}
          onExtensionChange={setExtensionValue}
          onFiltersChange={(columnId, filters) =>
            updateView((v) => ({
              ...v,
              filters: { ...v.filters, [columnId]: filters },
            }))
          }
        />
      )}

      <div style={{ display: 'flex' }}>
        <div
          data-testid="registry-table-block"
          style={{
            flex: 1,
            minHeight: 0,
            minWidth: 0,
            maxHeight: 720,
            overflowX: 'hidden',
            overflowY: 'auto',
            position: 'relative',
            background: tokenVar('surface'),
            borderRadius: RADII['radius-lg'],
          }}
        >
          {content}
        </div>
        {tabsPosition === 'right' && tables.length > 0 && (
          <TabStrip
            tables={tables}
            activeId={activeTableId}
            orientation="vertical"
            onSelect={setSelectedTab}
          />
        )}
      </div>
    </div>
  );
}
