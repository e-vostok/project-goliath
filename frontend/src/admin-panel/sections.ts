/**
 * The ONE registry of panel sections (0.11.0 unit 5a).
 *
 * The left menu and the `#/<slug>` hash routes are built from this
 * list — order here is the menu order. A later unit adds a section
 * by adding one folder under `sections/` and ONE line here; the
 * frame (`PanelFrame`) never needs editing.
 */

import type { ComponentType } from 'react';

import type { PanelIconName } from './panelIcons';
import { TurnSection } from './sections/turn/TurnSection';
import { PlayersSection } from './sections/players/PlayersSection';
import { NationsSection } from './sections/nations/NationsSection';
import { ProvincesSection } from './sections/provinces/ProvincesSection';
import { OrdersSection } from './sections/orders/OrdersSection';
import { AdminsSection } from './sections/admins/AdminsSection';
import { LogSection } from './sections/log/LogSection';

export interface PanelSectionDef {
  /** Hash route `#/<slug>` and the section's stable id. */
  slug: string;
  /** Menu label and section title. */
  title: string;
  icon: PanelIconName;
  component: ComponentType;
}

export const PANEL_SECTIONS: PanelSectionDef[] = [
  { slug: 'turn', title: 'Ход и мир', icon: 'clock', component: TurnSection },
  { slug: 'players', title: 'Игроки', icon: 'players', component: PlayersSection },
  { slug: 'nations', title: 'Государства', icon: 'flag', component: NationsSection },
  { slug: 'provinces', title: 'Провинции', icon: 'pin', component: ProvincesSection },
  { slug: 'orders', title: 'Приказы', icon: 'document', component: OrdersSection },
  { slug: 'admins', title: 'Администраторы', icon: 'shield', component: AdminsSection },
  { slug: 'log', title: 'Журнал', icon: 'list', component: LogSection },
];

export const DEFAULT_SECTION_SLUG = 'turn';

const SLUGS = new Set(PANEL_SECTIONS.map((s) => s.slug));

/** `#/players` → 'players'; anything else (incl. `#t=…`) → null. */
export function sectionSlugFromHash(hash: string): string | null {
  const match = /^#\/([a-z]+)$/.exec(hash);
  if (match === null || !SLUGS.has(match[1])) {
    return null;
  }
  return match[1];
}

export function sectionBySlug(slug: string): PanelSectionDef {
  return (
    PANEL_SECTIONS.find((s) => s.slug === slug) ??
    PANEL_SECTIONS.find((s) => s.slug === DEFAULT_SECTION_SLUG)!
  );
}
