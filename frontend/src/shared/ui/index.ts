/**
 * Shared UI library (version 0.9.0, unit 5): tokens, fonts, theme
 * mechanism and the custom elements of `docs/02_SYSTEM_SPECS/00_core_ui.md`.
 * Every window is built from this file's exports only.
 */

export * from './tokens';
export {
  BlockIcon,
  MarsIcon,
  MoonIcon,
  PencilIcon,
  SunIcon,
  VenusIcon,
} from './icons';
export type { BlockIconName } from './icons';
export { FieldLabel, FieldMessage, TextArea, TextField } from './fields';
export type {
  FieldLabelProps,
  TextAreaProps,
  TextFieldProps,
} from './fields';
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
export { NationLabel } from './NationLabel';
export { PortraitStub } from './PortraitStub';
export { ImageSlot, pickImageFile } from './ImageSlot';
export type {
  ImageSlotKind,
  ImageSlotProps,
  ImageSlotSize,
} from './ImageSlot';
export { LoadingState } from './LoadingState';
export { LoadingScreen, AuthErrorScreen } from './LoadingScreen';
export { Subscreen } from './Subscreen';
export { ErrorState, NETWORK_ERROR_TEXT } from './ErrorState';
export { EmptyState } from './EmptyState';
export { Popup, PopupHost } from './Popup';
export type { PopupProps, PopupSize } from './Popup';
export {
  NoticeHost,
  useNotice,
  NOTICE_TIMEOUT_MS,
  NOTICE_DANGER_TIMEOUT_MS,
} from './Notice';
export type { NoticeHostProps, NoticeTone, NotifyOptions } from './Notice';
export { Tooltip, TooltipRow, TOOLTIP_DELAY_MS } from './Tooltip';
export type { TooltipProps } from './Tooltip';
export { UiKitPage } from './UiKitPage';
export { UiKitEntry } from './UiKitEntry';
