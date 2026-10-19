/**
 * Shared UI library (version 0.9.0, unit 5): tokens, fonts, theme
 * mechanism and the custom elements of `docs/02_SYSTEM_SPECS/00_core_ui.md`.
 * Every window is built from this file's exports only.
 */

export * from './tokens';
export { BlockIcon, MoonIcon, SunIcon } from './icons';
export type { BlockIconName } from './icons';
export {
  ThemeProvider,
  ThemeToggle,
  useTheme,
  readStoredMode,
  writeStoredMode,
  schemeToTheme,
} from './theme';
export type {
  ThemeMode,
  ResolvedTheme,
  ThemeContextValue,
} from './theme';
export { BrandMark } from './BrandMark';
export { BlockTitle } from './BlockTitle';
export { StatTile } from './StatTile';
export { TurnBadge } from './TurnBadge';
export { ProvinceChip } from './ProvinceChip';
export { ColorSwatch } from './ColorSwatch';
export { FlagStub } from './FlagStub';
export { PortraitStub } from './PortraitStub';
export { LoadingState } from './LoadingState';
export { ErrorState, NETWORK_ERROR_TEXT } from './ErrorState';
export { EmptyState } from './EmptyState';
export { UiKitPage } from './UiKitPage';
export { UiKitEntry } from './UiKitEntry';
