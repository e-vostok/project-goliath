/**
 * PanelRegistry — the «Реестр» window (Spec 5.5).
 *
 * A column as tall as the app window: title row («Реестр» + «Назад»)
 * → tab row → toolbar (search, «Показано N из M», «Обновить»,
 * «Сбросить») → table block (flex:1; min-height:0; overflow-x:hidden,
 * overflow-y:auto, sticky header — the 910 px window rule: no
 * horizontal scrollbar, Spec 5.5). With layout.tabs_position = right the tab row becomes
 * a vertical column to the right of the table block. The page height
 * never depends on the row count.
 *
 * Sort, filters and search of each tab live in this component's state
 * and survive tab switches; leaving the panel («Назад») resets them
 * (Bible 2.7 — VKUI View keeps panels mounted, so the reset is done
 * explicitly, not by unmount).
 */

import { useMemo, useState } from 'react';
import { useRouteNavigator } from '@vkontakte/vk-mini-apps-router';
import { Button, FormStatus, Spinner, Title } from '@vkontakte/vkui';

import { useRegistryRows } from '../hooks/useRegistryRows';
import { useRegistryTables } from '../hooks/useRegistryTables';
import {
  applyView,
  EMPTY_VIEW,
  hasActiveFilters,
  nextSort,
  type TableView,
} from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import { RegistryTable } from './RegistryTable';
import { TableToolbar } from './TableToolbar';
import { TabStrip } from './TabStrip';

export function PanelRegistry() {
  const navigator = useRouteNavigator();
  const tablesState = useRegistryTables();
  const [selectedTab, setSelectedTab] = useState<string | null>(null);
  const [views, setViews] = useState<Record<string, TableView>>({});

  const tables = tablesState.data?.tables ?? [];
  const tabsPosition = tablesState.data?.layout.tabs_position ?? 'top';
  const activeTableId = selectedTab ?? tables[0]?.id ?? null;
  const activeTable = tables.find((t) => t.id === activeTableId) ?? null;

  const rows = useRegistryRows(activeTableId);

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

  const goBack = () => {
    setViews({});
    setSelectedTab(null);
    navigator.push('/');
  };

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
            onFiltersChange={(columnId, filters) =>
              updateView((v) => ({
                ...v,
                filters: { ...v.filters, [columnId]: filters },
              }))
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
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
        }}
      >
        <Title level="2">{REGISTRY_TEXTS.panelTitle}</Title>
        <Button mode="secondary" onClick={goBack}>
          {REGISTRY_TEXTS.back}
        </Button>
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
          onRefresh={rows.reload}
          refreshing={rows.refreshing}
          onReset={resetView}
          resetDisabled={!hasActiveFilters(view)}
        />
      )}

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <div
          data-testid="registry-table-block"
          style={{
            flex: 1,
            minHeight: 0,
            minWidth: 0,
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
