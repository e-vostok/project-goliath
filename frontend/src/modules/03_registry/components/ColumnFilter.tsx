/**
 * ColumnFilter — the per-column filter dropdown opened from the header
 * (Spec 5.5 / 3.7). The icon marks the column when a filter is active.
 * Filter kinds per column come from `column.filters`: text («Содержит»),
 * number_range («от/до», labelled by `filter_label` on date columns),
 * date_range (calendar inputs) and presence («есть/нет»).
 */

import { useState } from 'react';
import { Icon20FilterOutline } from '@vkontakte/icons';
import { Input } from '@vkontakte/vkui';

import {
  isFilterActive,
  type ColumnFilterValue,
} from '../lib/tableView';
import { REGISTRY_TEXTS } from '../texts';
import type { RegistryColumnDTO } from '../types';

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

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  opacity: 0.7,
  marginBottom: 2,
};

export function ColumnFilter({
  column,
  filters,
  onChange,
}: {
  column: RegistryColumnDTO;
  filters: ColumnFilterValue[];
  onChange: (filters: ColumnFilterValue[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = filters.some(isFilterActive);

  const kinds = column.filters;
  const text = fieldOf(filters, 'text');
  const range = fieldOf(filters, 'number_range');
  const dates = fieldOf(filters, 'date_range');
  const presence = fieldOf(filters, 'presence');

  const rangeLabel = column.filter_label ?? column.title;

  return (
    <span style={{ position: 'relative', display: 'inline-flex' }}>
      <button
        type="button"
        aria-label={REGISTRY_TEXTS.filterButtonAriaLabel(column.title)}
        data-testid={`filter-btn-${column.id}`}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          border: 0,
          background: 'transparent',
          padding: 2,
          cursor: 'pointer',
        }}
      >
        <Icon20FilterOutline
          fill={
            active
              ? 'var(--vkui--color_icon_accent)'
              : 'var(--vkui--color_icon_secondary)'
          }
        />
      </button>
      {open && (
        <div
          data-testid={`filter-pop-${column.id}`}
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            zIndex: 40,
            width: 260,
            padding: 12,
            borderRadius: 8,
            border: '1px solid var(--vkui--color_separator_primary)',
            background: 'var(--vkui--color_background_content)',
            boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          {kinds.includes('text') && (
            <div>
              <label style={labelStyle} htmlFor={`flt-txt-${column.id}`}>
                {REGISTRY_TEXTS.filterContainsLabel}
              </label>
              <Input
                id={`flt-txt-${column.id}`}
                value={text?.value ?? ''}
                onChange={(e) =>
                  onChange(
                    upsert(filters, { kind: 'text', value: e.target.value }),
                  )
                }
              />
            </div>
          )}
          {kinds.includes('number_range') && (
            <div>
              <label style={labelStyle}>{rangeLabel}</label>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input
                  type="number"
                  aria-label={`${rangeLabel}: ${REGISTRY_TEXTS.filterFromLabel}`}
                  placeholder={REGISTRY_TEXTS.filterFromLabel}
                  value={range?.from ?? ''}
                  onChange={(e) =>
                    onChange(
                      upsert(filters, {
                        kind: 'number_range',
                        from: e.target.value,
                        to: range?.to ?? '',
                      }),
                    )
                  }
                />
                <Input
                  type="number"
                  aria-label={`${rangeLabel}: ${REGISTRY_TEXTS.filterToLabel}`}
                  placeholder={REGISTRY_TEXTS.filterToLabel}
                  value={range?.to ?? ''}
                  onChange={(e) =>
                    onChange(
                      upsert(filters, {
                        kind: 'number_range',
                        from: range?.from ?? '',
                        to: e.target.value,
                      }),
                    )
                  }
                />
              </div>
            </div>
          )}
          {kinds.includes('date_range') && (
            <div>
              <label style={labelStyle}>{column.title}</label>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input
                  type="date"
                  aria-label={`${column.title}: ${REGISTRY_TEXTS.filterFromLabel}`}
                  value={dates?.from ?? ''}
                  onChange={(e) =>
                    onChange(
                      upsert(filters, {
                        kind: 'date_range',
                        from: e.target.value,
                        to: dates?.to ?? '',
                      }),
                    )
                  }
                />
                <Input
                  type="date"
                  aria-label={`${column.title}: ${REGISTRY_TEXTS.filterToLabel}`}
                  value={dates?.to ?? ''}
                  onChange={(e) =>
                    onChange(
                      upsert(filters, {
                        kind: 'date_range',
                        from: dates?.from ?? '',
                        to: e.target.value,
                      }),
                    )
                  }
                />
              </div>
            </div>
          )}
          {kinds.includes('presence') && (
            <div>
              <label style={labelStyle} htmlFor={`flt-prs-${column.id}`}>
                {REGISTRY_TEXTS.filterPresenceLabel}
              </label>
              <select
                id={`flt-prs-${column.id}`}
                aria-label={`${column.title}: ${REGISTRY_TEXTS.filterPresenceLabel}`}
                value={presence?.value ?? ''}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v !== 'has' && v !== 'none') {
                    onChange(filters.filter((f) => f.kind !== 'presence'));
                    return;
                  }
                  onChange(
                    upsert(filters, { kind: 'presence', value: v }),
                  );
                }}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  borderRadius: 8,
                  border: '1px solid var(--vkui--color_separator_primary)',
                  background: 'var(--vkui--color_background_content)',
                  color: 'inherit',
                }}
              >
                <option value="">{REGISTRY_TEXTS.presenceAny}</option>
                <option value="has">{REGISTRY_TEXTS.presenceHas}</option>
                <option value="none">{REGISTRY_TEXTS.presenceNone}</option>
              </select>
            </div>
          )}
        </div>
      )}
    </span>
  );
}
