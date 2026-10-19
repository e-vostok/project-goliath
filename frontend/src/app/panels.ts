/**
 * Panel ids of the main view — shared by the hash router (main.tsx),
 * the shell and the top bar. Kept in a tiny module of their own so
 * that the bar and the panels can read them without importing the
 * whole AppShell (which imports them back — a cycle).
 */

export const PANEL_HOME = 'nation-home';
export const PANEL_CREATE = 'nation-create';
export const PANEL_MAP = 'map';
export const PANEL_REGISTRY = 'registry';
