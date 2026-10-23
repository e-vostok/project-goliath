/**
 * NationMark — the author-nation snapshot (INV-O6): the shared
 * `NationLabel` with the submission-time SHORT name and flag (unit
 * 6a). Shared by the order detail window and the «Ожидают вердикт»
 * rows while they still exist.
 */

import { NationLabel } from '../../../shared/ui';
import type { NationMarkDTO } from '../types';

export function NationMark({ nation }: { nation: NationMarkDTO }) {
  return (
    <NationLabel
      name={nation.short_name}
      flagUrl={nation.flag_url}
      color={nation.color}
      size="cell"
    />
  );
}
