/**
 * TabStrip — the tabs of the «Реестр» (Spec 5.5, UI Spec 9.2).
 * `horizontal` is the row of signed text tabs («Игроки / Государства /
 * Приказы») sitting in the title row right after «РЕЕСТР» (layout.
 * tabs_position = top); `vertical` is the icon column to the right of
 * the table block (tabs_position = right). The table title is the
 * aria-label; on the icon column it is also the hover tooltip.
 */

import type { ComponentType } from 'react';
import {
  Icon28CheckShieldOutline,
  Icon28CoinsOutline,
  Icon28DocumentListOutline,
  Icon28FlagOutline,
  Icon28LocationMapOutline,
  Icon28MessagesOutline,
  Icon28TablecellsOutline,
  Icon28UsersOutline,
} from '@vkontakte/icons';

import { TEXT_STYLES, tokenVar } from '../../../shared/ui';

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
  orders: Icon28DocumentListOutline,
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

  // The horizontal strip lives inside the <h2> of the screen title, so
  // its root is a span (phrasing content) and every label resets the
  // inherited `title-uppercase` letterforms to plain `body` text.
  if (!vertical) {
    return (
      <span
        data-testid="registry-tabstrip"
        data-orientation={orientation}
        role="tablist"
        aria-orientation={orientation}
        style={{
          display: 'inline-flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: 4,
          marginLeft: 8,
        }}
      >
        {tables.map((table) => {
          const active = table.id === activeId;
          return (
            <button
              key={table.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={table.title}
              onClick={() => onSelect(table.id)}
              style={{
                padding: '4px 8px',
                border: 'none',
                borderBottom: `2px solid ${
                  active ? tokenVar('action') : 'transparent'
                }`,
                background: 'none',
                color: tokenVar(active ? 'ink' : 'ink-muted'),
                cursor: 'pointer',
                ...TEXT_STYLES.body,
                textTransform: 'none',
                letterSpacing: 'normal',
              }}
            >
              {table.title}
            </button>
          );
        })}
      </span>
    );
  }

  return (
    <div
      data-testid="registry-tabstrip"
      data-orientation={orientation}
      role="tablist"
      aria-orientation={orientation}
      style={{
        display: 'flex',
        flexDirection: 'column',
        flexWrap: 'nowrap',
        gap: 4,
        padding: '0 0 0 4px',
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
