/**
 * PanelRegistry — the «Реестр» window (Spec 5.5, UI Spec 9.2).
 *
 * An ordinary block in the page flow (the VK window follows the
 * content height — nothing here is pinned to it): title row
 * («Реестр») → tab row → toolbar (search, «Показано N из M»,
 * «Фильтры», «Обновить», «Сбросить») → the in-flow filter panel
 * (toggled by «Фильтры», normal document flow across the window
 * width) → table block (max-height 720 px; overflow-x:hidden,
 * overflow-y:auto, sticky header — the 910 px window rule: no
 * horizontal scrollbar, Spec 5.5). With layout.tabs_position = right
 * the tab row becomes a vertical column to the right of the table
 * block. The screen is as tall as its content. Navigation lives in
 * the shared top bar — no own «Назад».
 *
 * Sort, filters, search and the filter-panel toggle of each tab live
 * in this component's state and survive tab switches; leaving the
 * panel resets them (Bible 2.7 — VKUI View keeps panels mounted, so
 * the reset is done explicitly on the `active` prop flipping to
 * false, not by unmount).
 */

import { useEffect, useMemo, useState } from 'react';
import { Button, FormStatus, Spinner, Title } from '@vkontakte/vkui';

import { useNationOptions, NATIONS_TABLE_ID } from '../hooks/useNationOptions';
import { useRegistryRows } from '../hooks/useRegistryRows';
import { useRegistryTables } from '../hooks/useRegistryTables';
import { runCellAction } from '../lib/cellActions';
import { nationNamesOfRows } from '../lib/nationOptions';
import type { RegistryEntryRequest } from '../lib/entryRequest';
import {
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
}) {
  const tablesState = useRegistryTables();
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [views, setViews] = useState<Record<string, TableView>>({});
  const [pendingRequest, setPendingRequest] =
    useState<RegistryEntryRequest | null>(entryRequest);

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

  // Once the requested tab's rows are on screen, run the action — the
  // same call a cell click makes. `table_id` must match: on a tab
  // switch the hook still shows the previous table's rows for a beat.
  // A failed load leaves the request pending, so «Повторить» can run it.
  useEffect(() => {
    if (
      pendingRequest &&
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

  const shownRows = useMemo(
    () =>
      activeTable && rows.data
        ? applyView(activeTable, rows.data.rows, view)
        : [],
    [activeTable, rows.data, view],
  );

  const activeFilterCount = useMemo(
    () =>
      Object.values(view.filters).reduce(
        (sum, list) => sum + list.filter(isFilterActive).length,
        0,
      ),
    [view.filters],
  );

  // Leaving the screen is the old «Назад» reset — the panel stays
  // mounted inside VKUI View, so it is done explicitly when the
  // `active` flag drops (Bible 2.7).
  useEffect(() => {
    if (!active) {
      setViews({});
      setSelectedTab(null);
      setPendingRequest(null);
    }
  }, [active]);

  const resetView = () =>
    updateView((v) => ({ ...v, search: '', filters: {} }));

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
            {tablesState.error?.message}
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
            {rows.error?.message}
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
              {rows.error?.message}
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
        background: 'var(--vkui--color_background)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '8px 12px',
        }}
      >
        <Title level="2">{REGISTRY_TEXTS.panelTitle}</Title>
      </div>

      {tabsPosition === 'top' && tables.length > 0 && (
        <TabStrip
          tables={tables}
          activeId={activeTableId}
          orientation="horizontal"
          onSelect={setSelectedTab}
        />
      )}

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
          onRefresh={rows.reload}
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
