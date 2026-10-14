/**
 * TableToolbar — the row above the table (Spec 5.5): shared search,
 * «Показано N из M» counter, «Обновить» and «Сбросить».
 */

import { Button, Input } from '@vkontakte/vkui';

import { REGISTRY_TEXTS } from '../texts';

export function TableToolbar({
  search,
  onSearchChange,
  shown,
  total,
  onRefresh,
  refreshing,
  onReset,
  resetDisabled,
}: {
  search: string;
  onSearchChange: (value: string) => void;
  shown: number | null;
  total: number | null;
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
        padding: '0 12px 8px',
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
