/**
 * FilterPanel — the in-flow filter panel under the toolbar (Spec 5.5):
 * one labelled group per filterable column in a wrapping grid
 * (`repeat(auto-fill, minmax(200px, 1fr))`). It sits in the normal
 * document flow across the full window width minus the side padding,
 * so it can never float over the table or push the window sideways.
 * Filter kinds per column come from `column.filters`: text (one input
 * «содержит…»), number_range and date_range («от»/«до» pair, labelled
 * by `filter_label`), presence («Все / Есть / Нет») and
 * select_or_contains — a dropdown of the nations the Registry knows
 * (`nationOptions`) plus the same free-text «содержит…» input; the
 * two can be used independently. After the column groups come the
 * registered filter extensions of the table (Spec 5.5): one labelled
 * «Все / Да» control each, with the «Да» set's loading and error
 * states inside the group.
 */

import { Input, NativeSelect, SegmentedControl } from '@vkontakte/vkui';

import { errorText } from '../../../shared/errorTexts';
import { RADII, SPACING, tokenVar } from '../../../shared/ui';
import type {
  ExtensionSetState,
  TableFilterExtension,
} from '../lib/tableFilterExtensions';
import type { ColumnFilterValue, ExtensionFilterValue } from '../lib/tableView';
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

/** PNG 10 — the filter group's caption: 12/16 `ink-muted`. */
const GROUP_LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  lineHeight: '16px',
  color: tokenVar('ink-muted'),
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
  nationOptions = [],
  extensions = [],
  extensionValues = {},
  extensionStates = {},
  onExtensionChange,
}: {
  table: RegistryTableDTO;
  filters: Record<string, ColumnFilterValue[]>;
  onFiltersChange: (columnId: string, filters: ColumnFilterValue[]) => void;
  /** Dropdown options of `select_or_contains` columns (Spec 3.7). */
  nationOptions?: string[];
  /**
   * Filter extensions the table registered (Spec 5.5) — one labelled
   * «Все / Да» control per extension after the column groups; the
   * «Да» number set loads on demand and its status is shown inside
   * the same group.
   */
  extensions?: readonly TableFilterExtension[];
  extensionValues?: Record<string, ExtensionFilterValue>;
  extensionStates?: Record<string, ExtensionSetState>;
  onExtensionChange?: (extId: string, value: ExtensionFilterValue) => void;
}) {
  const filterable = table.columns.filter((col) => col.filters.length > 0);
  if (filterable.length === 0 && extensions.length === 0) {
    return null;
  }
  return (
    <div
      data-testid="registry-filter-panel"
      style={{
        margin: `0 0 ${SPACING['space-3']}px`,
        padding: SPACING['space-4'],
        borderRadius: RADII['radius-lg'],
        background: tokenVar('surface'),
        display: 'grid',
        gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
        gap: '12px 16px',
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
        const selectOrContains = fieldOf(list, 'select_or_contains');

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
              {col.filters.includes('select_or_contains') && (
                <>
                  <NativeSelect
                    aria-label={`${label}: ${REGISTRY_TEXTS.filterSelectLabel}`}
                    value={selectOrContains?.selected ?? ''}
                    onChange={(e) =>
                      onChange(
                        upsert(list, {
                          kind: 'select_or_contains',
                          selected: e.target.value,
                          contains: selectOrContains?.contains ?? '',
                        }),
                      )
                    }
                  >
                    <option value="">{REGISTRY_TEXTS.filterSelectAll}</option>
                    {nationOptions.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </NativeSelect>
                  <Input
                    aria-label={`${label}: ${REGISTRY_TEXTS.filterContainsLabel}`}
                    placeholder={REGISTRY_TEXTS.filterContainsPlaceholder}
                    value={selectOrContains?.contains ?? ''}
                    onChange={(e) =>
                      onChange(
                        upsert(list, {
                          kind: 'select_or_contains',
                          selected: selectOrContains?.selected ?? '',
                          contains: e.target.value,
                        }),
                      )
                    }
                  />
                </>
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
      {extensions.map((ext) => {
        const state = extensionStates[ext.id];
        return (
          <div key={ext.id} data-testid={`filter-ext-${ext.id}`}>
            <span style={GROUP_LABEL_STYLE}>{ext.label}</span>
            <SegmentedControl
              size="m"
              aria-label={ext.label}
              value={extensionValues[ext.id] ?? 'any'}
              onChange={(value) =>
                onExtensionChange?.(ext.id, value === 'yes' ? 'yes' : 'any')
              }
              options={[
                { label: REGISTRY_TEXTS.extFilterAll, value: 'any' },
                { label: REGISTRY_TEXTS.extFilterYes, value: 'yes' },
              ]}
            />
            {state?.status === 'loading' && (
              <span
                style={{
                  ...GROUP_LABEL_STYLE,
                  marginTop: 4,
                  fontWeight: 400,
                }}
              >
                {REGISTRY_TEXTS.extFilterLoading}
              </span>
            )}
            {state?.status === 'error' && (
              <span
                data-testid={`filter-ext-error-${ext.id}`}
                style={{
                  ...GROUP_LABEL_STYLE,
                  marginTop: 4,
                  fontWeight: 400,
                  color: 'var(--vkui--color_text_negative)',
                }}
              >
                {errorText(state.error)}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
