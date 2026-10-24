/**
 * TopBar — the app's permanent top bar (UI Spec 4; mockups
 * Main.dc.html / MainLight.dc.html, unit 4a of version 0.9.0).
 *
 * Height `topbar-h`, `surface` background, `line` below. Left: the
 * brand mark; then a real tablist «Штаб · Реестр · Карта» — the
 * active tab (by the active panel) is `ink` with a 2 px `action`
 * underline, the rest `ink-muted`. Right: the turn badge fed by the
 * game clock (hidden until the first answer arrives) and the theme
 * toggle. Replaces the temporary floating «Карта»/«Реестр» buttons.
 */

import { useRouteNavigator } from '@vkontakte/vk-mini-apps-router';

import { AdminPanelButton } from '../admin/AdminPanelButton';
import type { GameClockDTO } from '../shared/types';
import {
  BrandMark,
  SIZES,
  TEXT_STYLES,
  ThemeToggle,
  tokenVar,
  TurnBadge,
} from '../shared/ui';
import { PANEL_MAP, PANEL_REGISTRY } from './panels';

type TopTabId = 'hq' | 'registry' | 'map';

const TABS: { id: TopTabId; label: string; path: string }[] = [
  { id: 'hq', label: 'Штаб', path: '/' },
  { id: 'registry', label: 'Реестр', path: '/registry' },
  { id: 'map', label: 'Карта', path: '/map' },
];

/** «Штаб» hosts both the nation card and the registration screen. */
function activeTabOf(panel: string): TopTabId {
  if (panel === PANEL_REGISTRY) {
    return 'registry';
  }
  if (panel === PANEL_MAP) {
    return 'map';
  }
  return 'hq';
}

export function TopBar({
  activePanel,
  clock,
}: {
  activePanel: string;
  /** Null until the first /game-clock answer — the badge stays hidden. */
  clock: GameClockDTO | null;
}) {
  const navigator = useRouteNavigator();
  const activeTab = activeTabOf(activePanel);

  return (
    <header
      data-testid="topbar"
      style={{
        height: SIZES['topbar-h'],
        boxSizing: 'border-box',
        background: tokenVar('surface'),
        borderBottom: `1px solid ${tokenVar('line')}`,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: 24,
      }}
    >
      <BrandMark />
      <div
        role="tablist"
        style={{ display: 'flex', gap: 4, height: '100%', flexGrow: 1 }}
      >
        {TABS.map((tab) => {
          const selected = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => void navigator.push(tab.path)}
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                boxSizing: 'border-box',
                height: '100%',
                border: 'none',
                borderBottom: `2px solid ${
                  selected ? tokenVar('action') : 'transparent'
                }`,
                background: 'none',
                color: tokenVar(selected ? 'ink' : 'ink-muted'),
                cursor: 'pointer',
                ...TEXT_STYLES.body,
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {clock && (
          <TurnBadge>
            ХОД {clock.current_turn} · {clock.game_date_text.toUpperCase()}
          </TurnBadge>
        )}
        <AdminPanelButton />
        <ThemeToggle />
      </div>
    </header>
  );
}
