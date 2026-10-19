/**
 * AdminBlock — the «Админ» group at the bottom of the nation panels.
 *
 * Renders only for allowlisted admins (useAdminProbe). Four actions hit the
 * core/admin endpoints through the shared api-client; responses are shown
 * as pretty-printed JSON for the test cycle. «Сбросить мир» is destructive
 * and asks for inline confirmation before any request is sent.
 */

import { useEffect, useRef, useState } from 'react';
import bridge from '@vkontakte/vk-bridge';
import {
  Button,
  ButtonGroup,
  Div,
  Footnote,
  FormItem,
  FormStatus,
  Group,
  Header,
  Input,
  Spinner,
  Switch,
} from '@vkontakte/vkui';

import { api, ApiError } from '../shared/api-client';
import type { AdminPlayerDeleteResultDTO } from '../shared/types';
import { useSession } from '../modules/00_core/hooks/useAuth';
import { useAdminProbe } from './useAdminProbe';

const NETWORK_ERROR_MESSAGE = 'Ошибка сети — попробуйте ещё раз.';

const RESET_WARNING =
  'Будут удалены все государства, запланированные действия и журнал ' +
  'ходов, провинции освободятся, ход вернётся к 0. Игроки сохранятся. ' +
  'Отменить нельзя.';

const DELETE_WARNING =
  'Только для тестовых игроков. Удаляет игрока, его государство и все ' +
  'его данные во всех модулях. Отменить нельзя.';

const DELETE_ERROR_MESSAGES: Record<string, string> = {
  PLAYER_NOT_FOUND: 'Игрок с таким VK ID не найден.',
  CONFIRMATION_MISMATCH: 'Повторный VK ID не совпадает с указанным выше.',
  CANNOT_DELETE_SELF: 'Нельзя удалить собственного игрока.',
  CANNOT_DELETE_ADMIN: 'Нельзя удалить игрока из списка администраторов.',
};

function deleteErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    return DELETE_ERROR_MESSAGES[e.code] ?? `${e.message} (${e.code})`;
  }
  return NETWORK_ERROR_MESSAGE;
}

/** Plain-Russian summary of a delete-preview / delete result payload. */
function describePlayerDelete(p: AdminPlayerDeleteResultDTO): string {
  const parts: string[] = [
    p.nation_name === null
      ? 'Государства нет'
      : `Государство «${p.nation_name}» будет удалено, ` +
        `${p.provinces_released} провинций станут свободными`,
  ];
  const ordersDeleted = p.orders_author + p.orders_judge_decided;
  let ordersPart = `${ordersDeleted} приказов будет удалено`;
  if (p.orders_judge_undecided > 0) {
    ordersPart +=
      `, ${p.orders_judge_undecided} вернутся в очередь ` +
      'на нового судью';
  }
  parts.push(ordersPart);
  parts.push(
    `строк в очереди бота: ${p.outbox_rows}, ` +
      `согласий с ботом: ${p.consent_rows}, ` +
      `профилей в реестре: ${p.vk_profile_rows}`,
  );
  return parts.join('; ') + '.';
}

interface WindowMetrics {
  width: number;
  height: number;
  ratio: number;
  hasHorizontalScroll: boolean;
}

function readWindowMetrics(): WindowMetrics {
  return {
    width: window.innerWidth,
    height: window.innerHeight,
    ratio: window.devicePixelRatio,
    hasHorizontalScroll:
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  };
}

/** «Окно приложения» — live window metrics for the 0.9.0 layout probe. */
function WindowProbe() {
  const [metrics, setMetrics] = useState(readWindowMetrics);

  useEffect(() => {
    const refresh = () => setMetrics(readWindowMetrics());
    window.addEventListener('resize', refresh);
    return () => window.removeEventListener('resize', refresh);
  }, []);

  return (
    <Div data-testid="window-probe">
      <Header size="s" style={{ paddingLeft: 0 }}>
        Окно приложения
      </Header>
      <Footnote style={{ display: 'block' }}>
        Размер окна: {metrics.width} × {metrics.height} px
      </Footnote>
      <Footnote style={{ display: 'block' }}>
        Плотность пикселей: {metrics.ratio}
      </Footnote>
      <Footnote style={{ display: 'block' }}>
        Горизонтальная прокрутка:{' '}
        {metrics.hasHorizontalScroll ? 'есть' : 'нет'}
      </Footnote>
      <Button
        size="s"
        mode="tertiary"
        onClick={() => setMetrics(readWindowMetrics())}
      >
        Обновить
      </Button>
      <HeightProbe />
    </Div>
  );
}

const RESIZE_BUTTON_HEIGHTS = [1200, 2000, 3000, 4050] as const;
const HEIGHT_MIN = 600;
const HEIGHT_MAX = 4050;
const REREAD_DELAY_MS = 300;
const AUTOFIT_DEBOUNCE_MS = 200;

function contentHeight(): number {
  return Math.ceil(document.documentElement.scrollHeight);
}

function clampHeight(height: number): number {
  return Math.min(HEIGHT_MAX, Math.max(HEIGHT_MIN, height));
}

interface ResizeError {
  type: string;
  data: string;
}

interface ScrollPosition {
  scrollY: number;
  scrollTop: number;
  viewportHeight: number | null;
}

/**
 * «Высота окна» — experimental VKWebAppResizeWindow probe (0.9.0 unit 13).
 * Lets the admin resize the VK iframe by hand or follow the content height
 * automatically, and shows what the real VK answers.
 */
function HeightProbe() {
  const [reply, setReply] = useState<string | null>(null);
  const [error, setError] = useState<ResizeError | null>(null);
  const [reread, setReread] = useState<string | null>(null);
  const [autoFit, setAutoFit] = useState(false);
  const [autoCalls, setAutoCalls] = useState(0);
  const [autoLastHeight, setAutoLastHeight] = useState<number | null>(null);
  const [scrollPos, setScrollPos] = useState<ScrollPosition | null>(null);
  const rereadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (rereadTimer.current !== null) {
        clearTimeout(rereadTimer.current);
      }
    },
    [],
  );

  const sendResize = async (height: number) => {
    setReply(null);
    setError(null);
    setReread(null);
    if (rereadTimer.current !== null) {
      clearTimeout(rereadTimer.current);
    }
    try {
      const result = await bridge.send('VKWebAppResizeWindow', {
        width: window.innerWidth,
        height,
      });
      setReply(`Ответ VK: ${result.width} × ${result.height}`);
    } catch (e) {
      const err = e as { error_type?: string; error_data?: unknown };
      setError({
        type: err?.error_type ?? String(e),
        data:
          'error_data' in Object(err)
            ? (JSON.stringify(err.error_data) ?? 'нет')
            : 'нет',
      });
    }
    rereadTimer.current = setTimeout(() => {
      setReread(
        `Через 300 мс: ${window.innerWidth} × ${window.innerHeight}`,
      );
    }, REREAD_DELAY_MS);
  };

  useEffect(() => {
    if (!autoFit || typeof ResizeObserver === 'undefined') {
      return;
    }
    setAutoCalls(0);
    setAutoLastHeight(null);
    const target =
      document.getElementById('root') ?? document.documentElement;
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const observer = new ResizeObserver(() => {
      if (debounce !== null) {
        clearTimeout(debounce);
      }
      debounce = setTimeout(() => {
        const height = clampHeight(contentHeight());
        setAutoCalls((n) => n + 1);
        setAutoLastHeight(height);
        void bridge
          .send('VKWebAppResizeWindow', {
            width: window.innerWidth,
            height,
          })
          .catch(() => {});
      }, AUTOFIT_DEBOUNCE_MS);
    });
    observer.observe(target);
    return () => {
      observer.disconnect();
      if (debounce !== null) {
        clearTimeout(debounce);
      }
    };
  }, [autoFit]);

  const readScrollPosition = () =>
    setScrollPos({
      scrollY: window.scrollY,
      scrollTop: document.documentElement.scrollTop,
      viewportHeight: window.visualViewport?.height ?? null,
    });

  return (
    <div data-testid="height-probe">
      <Header size="s" style={{ paddingLeft: 0 }}>
        Высота окна
      </Header>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {RESIZE_BUTTON_HEIGHTS.map((h) => (
          <Button
            key={h}
            size="s"
            mode="secondary"
            onClick={() => void sendResize(h)}
          >
            {h}
          </Button>
        ))}
        <Button
          size="s"
          mode="secondary"
          onClick={() =>
            void sendResize(Math.max(HEIGHT_MIN, contentHeight()))
          }
        >
          По содержимому
        </Button>
      </div>
      {reply !== null && (
        <Footnote style={{ display: 'block' }}>{reply}</Footnote>
      )}
      {error !== null && (
        <>
          <Footnote style={{ display: 'block' }}>
            Ошибка VK: {error.type}
          </Footnote>
          <Footnote style={{ display: 'block' }}>
            error_data: {error.data}
          </Footnote>
        </>
      )}
      {reread !== null && (
        <Footnote style={{ display: 'block' }}>{reread}</Footnote>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 8,
        }}
      >
        <Switch
          checked={autoFit}
          onChange={(e) => setAutoFit(e.target.checked)}
          aria-label="Автоподстройка высоты"
        />
        <Footnote>Автоподстройка высоты</Footnote>
      </div>
      {autoFit && (
        <>
          <Footnote style={{ display: 'block' }}>
            Вызовов: {autoCalls}
          </Footnote>
          <Footnote style={{ display: 'block' }}>
            Последняя высота:{' '}
            {autoLastHeight === null ? '—' : `${autoLastHeight} px`}
          </Footnote>
        </>
      )}

      <Button
        size="s"
        mode="secondary"
        style={{ marginTop: 8 }}
        onClick={readScrollPosition}
      >
        Позиция прокрутки
      </Button>
      {scrollPos !== null && (
        <>
          <Footnote style={{ display: 'block' }}>
            window.scrollY: {scrollPos.scrollY}
          </Footnote>
          <Footnote style={{ display: 'block' }}>
            document.documentElement.scrollTop: {scrollPos.scrollTop}
          </Footnote>
          <Footnote style={{ display: 'block' }}>
            window.visualViewport.height:{' '}
            {scrollPos.viewportHeight ?? 'нет'}
          </Footnote>
        </>
      )}
    </div>
  );
}

export interface AdminBlockProps {
  /** Called after actions that mutate the world (tick, reset). */
  onWorldChanged: () => void;
}

export function AdminBlock({ onWorldChanged }: AdminBlockProps) {
  const { token } = useSession();
  const isAdmin = useAdminProbe();

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [output, setOutput] = useState<unknown>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [deleteTargetId, setDeleteTargetId] = useState('');
  const [deleteConfirmId, setDeleteConfirmId] = useState('');
  const [deletePreview, setDeletePreview] =
    useState<AdminPlayerDeleteResultDTO | null>(null);
  const [deleteDone, setDeleteDone] =
    useState<AdminPlayerDeleteResultDTO | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!expanded) {
      return;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setExpanded(false);
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [expanded]);

  const run = async (
    action: string,
    call: () => Promise<unknown>,
    worldChanged: boolean,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const data = await call();
      setLastAction(action);
      setOutput(data);
      if (worldChanged) {
        onWorldChanged();
      }
    } catch (e) {
      setError(
        e instanceof ApiError
          ? `${e.message} (${e.code})`
          : NETWORK_ERROR_MESSAGE,
      );
    } finally {
      setBusy(false);
    }
  };

  const deleteTarget = deleteTargetId.trim();
  const canDelete =
    deleteTarget !== '' && deleteTarget === deleteConfirmId.trim();

  const runDeletePreview = async () => {
    if (deleteTarget === '') {
      return;
    }
    setBusy(true);
    setDeleteError(null);
    setDeleteDone(null);
    try {
      setDeletePreview(
        await api.adminPlayerDeletePreview(token, deleteTarget),
      );
    } catch (e) {
      setDeletePreview(null);
      setDeleteError(deleteErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const runPlayerDelete = async () => {
    if (!canDelete) {
      return;
    }
    setBusy(true);
    setDeleteError(null);
    try {
      const result = await api.adminPlayerDelete(
        token,
        deleteTarget,
        deleteConfirmId.trim(),
      );
      setDeleteDone(result);
      setDeletePreview(null);
      setDeleteConfirmId('');
      onWorldChanged();
    } catch (e) {
      setDeleteError(deleteErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const copyOutput = () => {
    if (output === null) {
      return;
    }
    void navigator.clipboard
      ?.writeText(JSON.stringify(output, null, 2))
      .catch(() => {});
  };

  if (!isAdmin) {
    return null;
  }

  return (
    <Group header={<Header size="l">Админ</Header>}>
      {error && (
        <FormStatus mode="error" title="Действие не выполнено">
          {error}
        </FormStatus>
      )}

      <Div>
        <ButtonGroup stretched>
          <Button
            size="m"
            mode="secondary"
            disabled={busy}
            onClick={() =>
              void run('Состояние', () => api.adminState(token), false)
            }
          >
            Состояние
          </Button>
          <Button
            size="m"
            mode="secondary"
            disabled={busy}
            onClick={() =>
              void run('Журнал ходов', () => api.adminTickLog(token), false)
            }
          >
            Журнал ходов
          </Button>
          <Button
            size="m"
            mode="secondary"
            disabled={busy}
            onClick={() =>
              void run('Запустить ход', () => api.adminRunTick(token), true)
            }
          >
            Запустить ход
          </Button>
          <Button
            size="m"
            mode="primary"
            appearance="negative"
            disabled={busy}
            onClick={() => setConfirmingReset(true)}
          >
            Сбросить мир
          </Button>
        </ButtonGroup>
      </Div>

      <WindowProbe />

      {confirmingReset && (
        <Div>
          <Footnote style={{ display: 'block', marginBottom: 8 }}>
            {RESET_WARNING}
          </Footnote>
          <ButtonGroup stretched>
            <Button
              size="m"
              mode="primary"
              appearance="negative"
              disabled={busy}
              onClick={() => {
                setConfirmingReset(false);
                void run(
                  'Сбросить мир',
                  () => api.adminResetState(token),
                  true,
                );
              }}
            >
              Да, сбросить
            </Button>
            <Button
              size="m"
              mode="secondary"
              disabled={busy}
              onClick={() => setConfirmingReset(false)}
            >
              Отмена
            </Button>
          </ButtonGroup>
        </Div>
      )}

      <Div>
        <Header size="s" style={{ paddingLeft: 0 }}>
          Удаление игрока
        </Header>
        <Footnote style={{ display: 'block', marginBottom: 8 }}>
          {DELETE_WARNING}
        </Footnote>
        {deleteError && (
          <FormStatus mode="error" title="Действие не выполнено">
            {deleteError}
          </FormStatus>
        )}
        <FormItem top="VK ID игрока">
          <Input
            value={deleteTargetId}
            inputMode="numeric"
            aria-label="VK ID игрока"
            placeholder="Например, 123456789"
            onChange={(e) => {
              setDeleteTargetId(e.target.value);
              setDeletePreview(null);
              setDeleteDone(null);
            }}
          />
        </FormItem>
        <Button
          size="m"
          mode="secondary"
          disabled={busy || deleteTarget === ''}
          onClick={() => void runDeletePreview()}
        >
          Показать, что будет удалено
        </Button>
        {deletePreview !== null && (
          <Footnote
            data-testid="player-delete-preview"
            style={{ display: 'block', marginTop: 8 }}
          >
            {describePlayerDelete(deletePreview)}
          </Footnote>
        )}
        <FormItem top="Повторите VK ID для подтверждения">
          <Input
            value={deleteConfirmId}
            inputMode="numeric"
            aria-label="Повторите VK ID для подтверждения"
            onChange={(e) => setDeleteConfirmId(e.target.value)}
          />
        </FormItem>
        <Button
          size="m"
          mode="primary"
          appearance="negative"
          disabled={busy || !canDelete}
          onClick={() => void runPlayerDelete()}
        >
          Удалить безвозвратно
        </Button>
        {deleteDone !== null && (
          <FormStatus
            mode="default"
            title="Игрок удалён"
            data-testid="player-delete-result"
          >
            {describePlayerDelete(deleteDone)}
          </FormStatus>
        )}
      </Div>

      {(busy || output !== null) && (
        <Div>
          {busy ? (
            <>
              <Footnote style={{ display: 'block', marginBottom: 8 }}>
                Выполняется…
              </Footnote>
              <Spinner size="s" />
            </>
          ) : (
            <>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <Footnote>Результат: {lastAction}</Footnote>
                <div
                  style={{ display: 'flex', gap: 8, flexShrink: 0 }}
                >
                  <Button size="s" mode="tertiary" onClick={copyOutput}>
                    Скопировать
                  </Button>
                  <Button
                    size="s"
                    mode="tertiary"
                    onClick={() => setExpanded(true)}
                  >
                    Развернуть
                  </Button>
                </div>
              </div>
              <pre
                data-testid="admin-output"
                style={{
                  margin: 0,
                  padding: 8,
                  maxHeight: '40vh',
                  overflow: 'auto',
                  fontFamily: 'monospace',
                  fontSize: 12,
                  background: 'var(--vkui--color_background_secondary)',
                  borderRadius: 8,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {JSON.stringify(output, null, 2)}
              </pre>
            </>
          )}
        </Div>
      )}

      {expanded && output !== null && (
        <div
          data-testid="admin-output-overlay"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--vkui--color_background)',
          }}
        >
          <div
            style={{
              display: 'flex',
              gap: 8,
              padding: 12,
              borderBottom:
                '1px solid var(--vkui--color_separator_primary)',
            }}
          >
            <Button size="m" mode="secondary" onClick={copyOutput}>
              Скопировать
            </Button>
            <Button
              size="m"
              mode="secondary"
              onClick={() => setExpanded(false)}
            >
              Закрыть
            </Button>
          </div>
          <pre
            data-testid="admin-output-overlay-pre"
            style={{
              flex: 1,
              margin: 0,
              padding: 12,
              overflow: 'auto',
              fontFamily: 'monospace',
              fontSize: 12,
              whiteSpace: 'pre',
            }}
          >
            {JSON.stringify(output, null, 2)}
          </pre>
        </div>
      )}
    </Group>
  );
}
