/**
 * FilterPanel — the in-flow filter panel under the toolbar (Spec 5.5):
 * one labelled group per filterable column in a wrapping grid
 * (`repeat(auto-fill, minmax(200px, 1fr))`). It sits in the normal
 * document flow across the full window width minus the side padding,
 * so it can never float over the table or push the window sideways.
 * Filter kinds per column come from `column.filters`: text (one input
 * «содержит…»), number_range and date_range («от»/«до» pair, labelled
 * by `filter_label`) and presence («Все / Есть / Нет»).
 */

import { Input, SegmentedControl } from '@vkontakte/vkui';

import type { ColumnFilterValue } from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import type { RegistryTableDTO } from '../types';

function upsert(
  list: ColumnFilterValue[],
  next: ColumnFilterValue,
): ColumnFilterValue[] {
  const idx = list.findIndex((f) => f.kind === next.kind);
  if (idx === -1) {
    return [...list, next];
  }
  const copy = list.slice();
  copy[idx] = next;
  return copy;
}

function fieldOf<K extends ColumnFilterValue['kind']>(
  list: ColumnFilterValue[],
  kind: K,
): Extract<ColumnFilterValue, { kind: K }> | undefined {
  return list.find(
    (f): f is Extract<ColumnFilterValue, { kind: K }> => f.kind === kind,
  );
}

const GROUP_LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  fontWeight: 600,
  color: 'var(--vkui--color_text_secondary)',
  marginBottom: 4,
};

function RangeInputs({
  kind,
  inputType,
  label,
  range,
  onChange,
}: {
  kind: 'number_range' | 'date_range';
  inputType: 'number' | 'date';
  label: string;
  range: { from: string; to: string } | undefined;
  onChange: (next: ColumnFilterValue) => void;
}) {
  return (
    <div style={{ display: 'flex', gap: 8 }}>
      <Input
        type={inputType}
        aria-label={`${label}: ${REGISTRY_TEXTS.filterFromLabel}`}
        placeholder={REGISTRY_TEXTS.filterFromLabel}
        value={range?.from ?? ''}
        onChange={(e) =>
          onChange({ kind, from: e.target.value, to: range?.to ?? '' })
        }
      />
      <Input
        type={inputType}
        aria-label={`${label}: ${REGISTRY_TEXTS.filterToLabel}`}
        placeholder={REGISTRY_TEXTS.filterToLabel}
        value={range?.to ?? ''}
        onChange={(e) =>
          onChange({ kind, from: range?.from ?? '', to: e.target.value })
        }
      />
    </div>
  );
}

export function FilterPanel({
  table,
  filters,
  onFiltersChange,
}: {
  table: RegistryTableDTO;
  filters: Record<string, ColumnFilterValue[]>;
  onFiltersChange: (columnId: string, filters: ColumnFilterValue[]) => void;
}) {
  const filterable = table.columns.filter((col) => col.filters.length > 0);
  if (filterable.length === 0) {
    return null;
  }
  return (
    <div
      data-testid="registry-filter-panel"
      style={{
        margin: '0 12px 8px',
        padding: 12,
        borderRadius: 8,
        background: 'var(--vkui--color_background_content)',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
        gap: 12,
      }}
    >
      {filterable.map((col) => {
        const list = filters[col.id] ?? [];
        const onChange = (next: ColumnFilterValue[]) =>
          onFiltersChange(col.id, next);
        const label = col.filter_label ?? col.title;

        const text = fieldOf(list, 'text');
        const range = fieldOf(list, 'number_range');
        const dates = fieldOf(list, 'date_range');
        const presence = fieldOf(list, 'presence');

        return (
          <div key={col.id} data-testid={`filter-item-${col.id}`}>
            <span style={GROUP_LABEL_STYLE}>{label}</span>
            <div
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              {col.filters.includes('text') && (
                <Input
                  aria-label={`${label}: ${REGISTRY_TEXTS.filterContainsLabel}`}
                  placeholder={REGISTRY_TEXTS.filterContainsPlaceholder}
                  value={text?.value ?? ''}
                  onChange={(e) =>
                    onChange(
                      upsert(list, { kind: 'text', value: e.target.value }),
                    )
                  }
                />
              )}
              {col.filters.includes('number_range') && (
                <RangeInputs
                  kind="number_range"
                  inputType="number"
                  label={label}
                  range={range}
                  onChange={(next) => onChange(upsert(list, next))}
                />
              )}
              {col.filters.includes('date_range') && (
                <RangeInputs
                  kind="date_range"
                  inputType="date"
                  label={label}
                  range={dates}
                  onChange={(next) => onChange(upsert(list, next))}
                />
              )}
              {col.filters.includes('presence') && (
                <SegmentedControl
                  size="m"
                  aria-label={`${label}: ${REGISTRY_TEXTS.filterPresenceLabel}`}
                  value={presence?.value ?? 'any'}
                  onChange={(value) => {
                    if (value !== 'has' && value !== 'none') {
                      onChange(list.filter((f) => f.kind !== 'presence'));
                      return;
                    }
                    onChange(upsert(list, { kind: 'presence', value }));
                  }}
                  options={[
                    { label: REGISTRY_TEXTS.presenceAny, value: 'any' },
                    { label: REGISTRY_TEXTS.presenceHas, value: 'has' },
                    { label: REGISTRY_TEXTS.presenceNone, value: 'none' },
                  ]}
                />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
