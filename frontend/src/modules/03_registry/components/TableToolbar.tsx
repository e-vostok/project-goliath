/**
 * TableToolbar — the row above the table (Spec 5.5): shared search,
 * «Показано N из M» counter, «Фильтры» (opens the in-flow filter
 * panel, badge = number of active filters), «Обновить» and «Сбросить».
 */

import { Button, Input } from '@vkontakte/vkui';

import { SPACING } from '../../../shared/ui';

import { REGISTRY_TEXTS } from '../texts';

export function TableToolbar({
  search,
  onSearchChange,
  shown,
  total,
  filtersOpen,
  activeFilterCount,
  onToggleFilters,
  onRefresh,
  refreshing,
  onReset,
  resetDisabled,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  shown: number | null;
  total: number | null;
  filtersOpen: boolean;
  activeFilterCount: number;
  onToggleFilters: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  onReset: () => void;
  resetDisabled: boolean;
}) {
  return (
    <div
      data-testid="registry-toolbar"
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 8,
        paddingBottom: SPACING['space-3'],
      }}
    >
      <div style={{ flex: 1, maxWidth: 360 }}>
        <Input
          value={search}
          placeholder={REGISTRY_TEXTS.searchPlaceholder}
          onChange={(e) => onSearchChange(e.target.value)}
          aria-label={REGISTRY_TEXTS.searchPlaceholder}
        />
      </div>
      <span
        data-testid="registry-counter"
        style={{ opacity: 0.7, whiteSpace: 'nowrap' }}
      >
        {shown !== null && total !== null
          ? REGISTRY_TEXTS.shownCounter(shown, total)
          : ''}
      </span>
      <span style={{ flex: 1 }} />
      <Button
        size="s"
        mode={filtersOpen ? 'primary' : 'secondary'}
        data-testid="filters-toggle"
        onClick={onToggleFilters}
      >
        {REGISTRY_TEXTS.filtersButton}
        {activeFilterCount > 0 && (
          <span
            data-testid="filters-count"
            style={{
              marginLeft: 6,
              padding: '0 6px',
              borderRadius: 8,
              fontSize: 12,
              lineHeight: '16px',
              background: 'var(--vkui--color_background_accent_themed)',
              color: 'var(--vkui--color_text_contrast_themed)',
            }}
          >
            {activeFilterCount}
          </span>
        )}
      </Button>
      <Button
        size="s"
        mode="secondary"
        onClick={onRefresh}
        disabled={refreshing}
      >
        {REGISTRY_TEXTS.refresh}
      </Button>
      <Button
        size="s"
        mode="secondary"
        onClick={onReset}
        disabled={resetDisabled}
      >
        {REGISTRY_TEXTS.reset}
      </Button>
    </div>
  );
}
