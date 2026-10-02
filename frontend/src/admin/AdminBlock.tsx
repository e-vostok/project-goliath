/**
 * AdminBlock — the «Админ» group at the bottom of the nation panels.
 *
 * Renders only for allowlisted admins (useAdminProbe). Four actions hit the
 * core/admin endpoints through the shared api-client; responses are shown
 * as pretty-printed JSON for the test cycle. «Сбросить мир» is destructive
 * and asks for inline confirmation before any request is sent.
 */

import { useEffect, useState } from 'react';
import {
  Button,
  ButtonGroup,
  Div,
  Footnote,
  FormStatus,
  Group,
  Header,
  Spinner,
} from '@vkontakte/vkui';

import { api, ApiError } from '../shared/api-client';
import { useSession } from '../modules/00_core/hooks/useAuth';
import { E1ProbePanel } from '../dev/e1_probe/E1ProbePanel';
import { useAdminProbe } from './useAdminProbe';

const NETWORK_ERROR_MESSAGE = 'Ошибка сети — попробуйте ещё раз.';

const RESET_WARNING =
  'Будут удалены все государства, запланированные действия и журнал ' +
  'ходов, провинции освободятся, ход вернётся к 0. Игроки сохранятся. ' +
  'Отменить нельзя.';

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

      <E1ProbePanel />
    </Group>
  );
}
