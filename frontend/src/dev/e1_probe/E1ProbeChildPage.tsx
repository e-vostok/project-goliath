/**
 * E1ProbeChildPage — standalone child tab for probe E.
 *
 * Rendered INSTEAD of the app when the entry hash is '#e1-probe-child':
 * no VK Bridge init, no auth, no API calls. Plain HTML only, so it needs
 * no VKUI providers. Shows the browser metrics, a fullscreen button with
 * its outcome, and a ready-to-copy report for the Owner to send back.
 */

import { useMemo, useRef, useState } from 'react';

import { collectMetrics } from './helpers';
import { runFullscreenProbe } from './probes';
import { buildReport } from './report';
import type { ProbeBlock } from './types';

export function E1ProbeChildPage() {
  const logRef = useRef<HTMLTextAreaElement>(null);
  const [blocks, setBlocks] = useState<ProbeBlock[]>(() => [
    {
      probe: 'CHILD',
      label: 'Дочерняя вкладка (вне окружения ВК)',
      at: new Date().toISOString(),
      ok: true,
      result: { metrics: collectMetrics(window, document) },
    },
  ]);
  const [fsOutcome, setFsOutcome] = useState<string | null>(null);

  const report = useMemo(
    () => buildReport(blocks, 'e1-probe-child'),
    [blocks],
  );

  const goFullscreen = async () => {
    const block = await runFullscreenProbe(
      'C',
      'Полный экран: вся страница',
      document.documentElement,
      window,
      document,
    );
    setBlocks((prev) => [...prev, block]);
    setFsOutcome(
      block.ok
        ? 'resolved — полный экран запрошен (Esc выходит)'
        : `${block.error?.name}: ${block.error?.message}`,
    );
  };

  return (
    <div
      style={{
        fontFamily: 'sans-serif',
        padding: 24,
        maxWidth: 900,
        margin: '0 auto',
        lineHeight: 1.5,
      }}
    >
      <h1>E1 — дочерняя вкладка</h1>
      <p>
        Эта страница открыта как обычная вкладка браузера: VK Bridge не
        инициализирован, авторизации и запросов к API нет. Если здесь
        «Полный экран» работает, а внутри ВК — нет, значит ограничение даёт
        именно iframe ВКонтакте.
      </p>

      <p>
        <button
          type="button"
          onClick={() => void goFullscreen()}
          style={{ fontSize: 16, padding: '8px 16px' }}
        >
          Полный экран: вся страница
        </button>
        {fsOutcome && <span style={{ marginLeft: 12 }}>{fsOutcome}</span>}
      </p>

      <h2>Скопируйте это и пришлите:</h2>
      <textarea
        ref={logRef}
        data-testid="e1-child-report"
        readOnly
        value={report}
        onFocus={(e) => e.target.select()}
        style={{
          width: '100%',
          minHeight: 320,
          fontFamily: 'monospace',
          fontSize: 12,
          boxSizing: 'border-box',
          padding: 8,
        }}
      />
    </div>
  );
}
