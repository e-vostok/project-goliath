/**
 * E1ProbePanel — temporary admin-only experiment «Проба большого окна (E1)».
 *
 * One button per probe (A–F); every click appends a result block to the
 * shared monospace report below. «Скопировать отчёт» uses the clipboard API
 * and falls back to selecting the textarea for Ctrl+C — which path was used
 * is itself appended to the log.
 */

import { useMemo, useRef, useState } from 'react';
import realBridge from '@vkontakte/vk-bridge';
import {
  Button,
  ButtonGroup,
  Div,
  Footnote,
  FormItem,
  Group,
  Header,
  Input,
} from '@vkontakte/vkui';

import { buildReport } from './report';
import {
  RESIZE_PRESETS,
  runEnvironmentProbe,
  runFullscreenProbe,
  runOpenTabProbe,
  runOpenVkAppProbe,
  runResizeProbe,
  type BridgeLike,
} from './probes';
import type { ProbeBlock } from './types';

export interface E1ProbePanelProps {
  /** Injectable for tests; defaults to the real VK bridge. */
  bridge?: BridgeLike;
}

export function E1ProbePanel({ bridge }: E1ProbePanelProps) {
  const vkBridge: BridgeLike =
    bridge ?? (realBridge as unknown as BridgeLike);

  const containerRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLTextAreaElement>(null);
  const [blocks, setBlocks] = useState<ProbeBlock[]>([]);
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [copyHint, setCopyHint] = useState<string | null>(null);

  const report = useMemo(() => buildReport(blocks, label), [blocks, label]);

  const append = (block: ProbeBlock) =>
    setBlocks((prev) => [...prev, block]);

  const run = async (fn: () => Promise<ProbeBlock> | ProbeBlock) => {
    setBusy(true);
    try {
      append(await fn());
    } finally {
      setBusy(false);
    }
  };

  const exitFullscreen = () => {
    try {
      if (
        document.fullscreenElement &&
        typeof document.exitFullscreen === 'function'
      ) {
        void document.exitFullscreen().catch(() => {});
      }
    } catch {
      // Fullscreen state unreadable — nothing to exit.
    }
  };

  const copyReport = async () => {
    let method: 'clipboard' | 'manual-select';
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error('clipboard API unavailable');
      }
      await navigator.clipboard.writeText(report);
      method = 'clipboard';
      setCopyHint('Скопировано в буфер обмена.');
    } catch {
      const textarea = logRef.current;
      if (textarea) {
        textarea.focus();
        textarea.select();
      }
      method = 'manual-select';
      setCopyHint(
        'Буфер обмена недоступен — текст выделен, нажмите Ctrl+C.',
      );
    }
    append({
      probe: 'COPY',
      label: 'Скопировать отчёт',
      at: new Date().toISOString(),
      ok: true,
      result: { method },
    });
  };

  return (
    <Group header={<Header size="s">Проба большого окна (E1)</Header>}>
      <div ref={containerRef} data-testid="e1-probe-container">
        <Div>
          <Footnote style={{ display: 'block' }}>
            Временная панель эксперимента. Каждая кнопка добавляет блок в
            отчёт ниже. Полный экран закрывается клавишей Esc или кнопкой
            «Выйти из полного экрана».
          </Footnote>
        </Div>

        <FormItem top="Метка прогона">
          <Input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="например, wide_off"
          />
        </FormItem>

        <Div>
          <ButtonGroup mode="vertical" stretched gap="s">
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  runEnvironmentProbe(vkBridge, window, document),
                )
              }
            >
              Среда
            </Button>
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  runFullscreenProbe(
                    'B',
                    'Полный экран: этот блок',
                    containerRef.current ?? {},
                    window,
                    document,
                  ),
                )
              }
            >
              Полный экран: этот блок
            </Button>
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  runFullscreenProbe(
                    'C',
                    'Полный экран: вся страница',
                    document.documentElement,
                    window,
                    document,
                  ),
                )
              }
            >
              Полный экран: вся страница
            </Button>
          </ButtonGroup>
        </Div>

        <Div>
          <Footnote style={{ display: 'block', marginBottom: 8 }}>
            Изменить размер окна ВК:
          </Footnote>
          <ButtonGroup stretched gap="s" style={{ flexWrap: 'wrap' }}>
            {RESIZE_PRESETS.map((preset) => (
              <Button
                key={`${preset.width}x${preset.height}`}
                size="s"
                mode="secondary"
                disabled={busy}
                onClick={() =>
                  void run(() =>
                    runResizeProbe(
                      preset.width,
                      preset.height,
                      vkBridge,
                      window,
                      document,
                    ),
                  )
                }
              >
                {preset.width}×{preset.height}
              </Button>
            ))}
          </ButtonGroup>
        </Div>

        <Div>
          <ButtonGroup mode="vertical" stretched gap="s">
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() => void run(async () => runOpenTabProbe(window))}
            >
              Новая вкладка (наш адрес)
            </Button>
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() =>
                void run(() => runOpenVkAppProbe(vkBridge, window))
              }
            >
              Новая вкладка (адрес приложения во ВК)
            </Button>
            <Button size="m" mode="secondary" onClick={exitFullscreen}>
              Выйти из полного экрана
            </Button>
          </ButtonGroup>
        </Div>

        <Div>
          <textarea
            ref={logRef}
            data-testid="e1-report"
            readOnly
            value={report}
            style={{
              width: '100%',
              minHeight: 240,
              margin: 0,
              padding: 8,
              fontFamily: 'monospace',
              fontSize: 12,
              boxSizing: 'border-box',
              background: 'var(--vkui--color_background_secondary)',
              color: 'var(--vkui--color_text_primary)',
              border:
                '1px solid var(--vkui--color_field_border_alpha)',
              borderRadius: 8,
            }}
          />
        </Div>

        {copyHint && (
          <Div>
            <Footnote style={{ display: 'block' }}>{copyHint}</Footnote>
          </Div>
        )}

        <Div>
          <ButtonGroup stretched gap="s">
            <Button
              size="m"
              mode="secondary"
              onClick={() => void copyReport()}
            >
              Скопировать отчёт
            </Button>
            <Button
              size="m"
              mode="secondary"
              onClick={() => {
                setBlocks([]);
                setCopyHint(null);
              }}
            >
              Очистить
            </Button>
          </ButtonGroup>
        </Div>
      </div>
    </Group>
  );
}
