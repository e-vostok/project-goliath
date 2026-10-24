/**
 * FilterPanel — the in-flow filter panel under the toolbar (Spec 5.5):
 * one labelled group per filterable column in a strict three-column
 * grid (`repeat(3, minmax(0, 1fr))`). It sits in the normal document
 * flow across the full window width minus the side padding, so it can
 * never float over the table or push the window sideways.
 *
 * The unit-13b grid rule (PNG 09c/10/10b): ONE GROUP = ONE GRID CELL =
 * the 12/16 `ink-muted` label plus EXACTLY ONE ROW of controls, every
 * control 36 px high and shrinkable (`min-width: 0` on the VKUI
 * wrapper is what stops a control from running out of its cell). What
 * the row holds depends on the column's filter kinds (`filters`): a
 * `text` column gets one «содержит…» input; `number_range` and
 * `date_range` get the «от»/«до» pair side by side (50/50); a
 * `select_or_contains` column gets the nations dropdown (3 parts) and
 * the «содержит…» input (2 parts) in the same row — the two halves
 * filter independently. A `presence` filter never shares the column's
 * group: it becomes its OWN grid cell right after it, labelled
 * «<столбец>: наличие», with the «Все / Есть / Нет» segmented control.
 * After the column cells come the registered filter extensions of the
 * table (Spec 5.5): one labelled «Все / Да» cell each, with the «Да»
 * set's loading and error states inside it.
 */

import { Fragment } from 'react';

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

/** PNG 09c — the filter cell's caption: 12/16 `ink-muted`. */
const GROUP_LABEL_STYLE: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  lineHeight: '16px',
  color: tokenVar('ink-muted'),
  marginBottom: 4,
};

/**
 * Every control of the one row: 36 px high and allowed to shrink below
 * its content size — VKUI field wrappers keep their own min-width and
 * would otherwise run out of the cell.
 */
const CONTROL_STYLE: React.CSSProperties = {
  height: 36,
  minWidth: 0,
};

/** The cell's single control row; controls never wrap to a second one. */
const CONTROL_ROW_STYLE: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  minWidth: 0,
};

function RangeInputs({
  kind,
  inputType,
  label,
  scaleMin = null,
  scaleMax = null,
  range,
  onChange,
}: {
  kind: 'number_range' | 'date_range';
  inputType: 'number' | 'date';
  label: string;
  /**
   * A scaled column (the players' «Рейтинг» — `scale_min`/`scale_max`
   * of the DTO) writes the bounds into the placeholders:
   * «от −100» / «до +100»; other ranges keep «от»/«до».
   */
  scaleMin?: number | null;
  scaleMax?: number | null;
  range: { from: string; to: string } | undefined;
  onChange: (next: ColumnFilterValue) => void;
}) {
  const fromPlaceholder =
    scaleMin !== null
      ? REGISTRY_TEXTS.filterFromWithBound(scaleMin)
      : REGISTRY_TEXTS.filterFromLabel;
  const toPlaceholder =
    scaleMax !== null
      ? REGISTRY_TEXTS.filterToWithBound(scaleMax)
      : REGISTRY_TEXTS.filterToLabel;
  return (
    <>
      <Input
        type={inputType}
        style={{ ...CONTROL_STYLE, flex: '1 1 0' }}
        aria-label={`${label}: ${REGISTRY_TEXTS.filterFromLabel}`}
        placeholder={fromPlaceholder}
        value={range?.from ?? ''}
        onChange={(e) =>
          onChange({ kind, from: e.target.value, to: range?.to ?? '' })
        }
      />
      <Input
        type={inputType}
        style={{ ...CONTROL_STYLE, flex: '1 1 0' }}
        aria-label={`${label}: ${REGISTRY_TEXTS.filterToLabel}`}
        placeholder={toPlaceholder}
        value={range?.to ?? ''}
        onChange={(e) =>
          onChange({ kind, from: range?.from ?? '', to: e.target.value })
        }
      />
    </>
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
   * «Все / Да» cell per extension after the column cells; the «Да»
   * number set loads on demand and its status is shown inside the same
   * cell.
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
          <Fragment key={col.id}>
            <div
              data-testid={`filter-item-${col.id}`}
              style={{ minWidth: 0 }}
            >
              <span style={GROUP_LABEL_STYLE}>{label}</span>
              <div style={CONTROL_ROW_STYLE}>
                {col.filters.includes('text') && (
                  <Input
                    style={{ ...CONTROL_STYLE, flex: '1 1 0' }}
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
                    scaleMin={col.scale_min}
                    scaleMax={col.scale_max}
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
                      style={{ ...CONTROL_STYLE, flex: '3 1 0' }}
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
                      style={{ ...CONTROL_STYLE, flex: '2 1 0' }}
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
              </div>
            </div>
            {col.filters.includes('presence') && (
              <div
                data-testid={`filter-item-${col.id}-presence`}
                style={{ minWidth: 0 }}
              >
                <span style={GROUP_LABEL_STYLE}>
                  {REGISTRY_TEXTS.filterPresenceTitle(label)}
                </span>
                <SegmentedControl
                  size="m"
                  style={CONTROL_STYLE}
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
              </div>
            )}
          </Fragment>
        );
      })}
      {extensions.map((ext) => {
        const state = extensionStates[ext.id];
        return (
          <div
            key={ext.id}
            data-testid={`filter-ext-${ext.id}`}
            style={{ minWidth: 0 }}
          >
            <span style={GROUP_LABEL_STYLE}>{ext.label}</span>
            <SegmentedControl
              size="m"
              style={CONTROL_STYLE}
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
