/**
 * Report builder for the E1 probe panel. A pure function: blocks separated
 * by `----`, values pretty-printed with 2-space indent, header lines state
 * the panel version and the user-entered run label.
 */

import type { ProbeBlock } from './types';

export const E1_REPORT_VERSION = 'E1-1';

export function buildReport(blocks: ProbeBlock[], label: string): string {
  const header = `${E1_REPORT_VERSION}\nМетка прогона: ${label || '(пусто)'}`;
  if (blocks.length === 0) {
    return `${header}\n(проб ещё нет)`;
  }
  const body = blocks
    .map((block) => `----\n${JSON.stringify(block, null, 2)}`)
    .join('\n');
  return `${header}\n${body}`;
}
