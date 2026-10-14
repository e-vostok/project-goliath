/**
 * TabStrip — one icon tab per table (Spec 5.5). `horizontal` is the row
 * under the title (layout.tabs_position = top); `vertical` is the column
 * to the right of the table block (tabs_position = right). The table
 * title is the hover tooltip and the aria-label; unknown icon names
 * fall back to a generic table icon.
 */

import type { ComponentType } from 'react';
import {
  Icon28CheckShieldOutline,
  Icon28CoinsOutline,
  Icon28FlagOutline,
  Icon28LocationMapOutline,
  Icon28MessagesOutline,
  Icon28TablecellsOutline,
  Icon28UsersOutline,
} from '@vkontakte/icons';

import type { RegistryTableDTO } from '../types';

type IconComponent = ComponentType<{ fill?: string }>;

/** Config `icon` name → @vkontakte/icons (generic fallback below). */
const TAB_ICONS: Record<string, IconComponent> = {
  players: Icon28UsersOutline,
  nations: Icon28FlagOutline,
  map: Icon28LocationMapOutline,
  economy: Icon28CoinsOutline,
  army: Icon28CheckShieldOutline,
  diplomacy: Icon28MessagesOutline,
  table: Icon28TablecellsOutline,
};

const GENERIC_ICON = Icon28TablecellsOutline;

export function TabStrip({
  tables,
  activeId,
  orientation,
  onSelect,
}: {
  tables: RegistryTableDTO[];
  activeId: string | null;
  orientation: 'horizontal' | 'vertical';
  onSelect: (tableId: string) => void;
}) {
  const vertical = orientation === 'vertical';
  return (
    <div
      data-testid="registry-tabstrip"
      data-orientation={orientation}
      role="tablist"
      aria-orientation={orientation}
      style={{
        display: 'flex',
        flexDirection: vertical ? 'column' : 'row',
        flexWrap: vertical ? 'nowrap' : 'wrap',
        gap: 4,
        padding: vertical ? '0 12px 0 4px' : '0 12px 8px',
      }}
    >
      {tables.map((table) => {
        const Icon = TAB_ICONS[table.icon] ?? GENERIC_ICON;
        const active = table.id === activeId;
        return (
          <button
            key={table.id}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={table.title}
            title={table.title}
            onClick={() => onSelect(table.id)}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 40,
              height: 40,
              flexShrink: 0,
              borderRadius: 8,
              border: active
                ? '2px solid var(--vkui--color_stroke_accent)'
                : '1px solid var(--vkui--color_separator_primary)',
              background: active
                ? 'var(--vkui--color_background_secondary)'
                : 'transparent',
              cursor: 'pointer',
            }}
          >
            <Icon
              fill={
                active
                  ? 'var(--vkui--color_icon_accent)'
                  : 'var(--vkui--color_icon_secondary)'
              }
            />
          </button>
        );
      })}
    </div>
  );
}
