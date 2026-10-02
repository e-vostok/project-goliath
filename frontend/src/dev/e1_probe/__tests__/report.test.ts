/**
 * buildReport — header carries the E1-1 version and the run label; blocks
 * are separated by `----` and pretty-printed; the output must never
 * contain secret-looking strings when fed clean blocks.
 */

import { buildReport, E1_REPORT_VERSION } from '../report';
import type { ProbeBlock } from '../types';

const BLOCK_A: ProbeBlock = {
  probe: 'A',
  label: 'Среда',
  at: '2026-10-02T12:00:00.000Z',
  ok: true,
  result: { metrics: { innerWidth: 1000 } },
};

const BLOCK_D: ProbeBlock = {
  probe: 'D',
  label: 'Изменить размер окна ВК 1400×1200',
  at: '2026-10-02T12:00:10.000Z',
  ok: false,
  error: {
    name: 'client_error',
    message: '{"error_code":1}',
    error_type: 'client_error',
    error_data: { error_code: 1 },
  },
};

describe('buildReport', () => {
  it('starts with the version and the run label', () => {
    const report = buildReport([BLOCK_A], 'wide_off');
    const lines = report.split('\n');
    expect(lines[0]).toBe(E1_REPORT_VERSION);
    expect(lines[1]).toBe('Метка прогона: wide_off');
  });

  it('separates every block with ---- and pretty-prints JSON', () => {
    const report = buildReport([BLOCK_A, BLOCK_D], 'x');
    expect(report.split('\n----\n')).toHaveLength(2 + 1); // header + 2 blocks
    expect(report).toContain('"probe": "A"');
    expect(report).toContain('"probe": "D"');
    expect(report).toContain('"error_type": "client_error"');
    expect(report).toContain(JSON.stringify(BLOCK_A, null, 2));
    expect(report).toContain(JSON.stringify(BLOCK_D, null, 2));
  });

  it('annotates an empty log instead of printing nothing', () => {
    expect(buildReport([], 'x')).toContain('(проб ещё нет)');
  });

  it('contains no secret-looking strings for clean blocks', () => {
    const report = buildReport([BLOCK_A, BLOCK_D], 'wide_on');
    expect(report).not.toContain('sign=');
    expect(report).not.toContain('access_token');
  });
});
