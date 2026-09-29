/**
 * AdminBlock — the «Админ» group at the bottom of the nation panels.
 *
 * Renders only for allowlisted admins (useAdminProbe). Four actions hit the
 * core/admin endpoints through the shared api-client; responses are shown
 * as pretty-printed JSON for the test cycle. «Сбросить мир» is destructive
 * and asks for inline confirmation before any request is sent.
 */

import { useState } from 'react';
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
import { useAdminProbe } from './useAdminProbe';

const NETWORK_ERROR_MESSAGE = 'Ошибка сети — попробуйте ещё раз.';

const RESET_WARNING =
  'Будут удалены все государства и запланированные действия, провинции ' +
  'освободятся, ход вернётся к 0. Игроки и журнал ходов сохранятся. ' +
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
          <Footnote style={{ display: 'block', marginBottom: 8 }}>
            {busy ? 'Выполняется…' : `Результат: ${lastAction}`}
          </Footnote>
          {busy ? (
            <Spinner size="s" />
          ) : (
            <>
              <pre
                data-testid="admin-output"
                style={{
                  margin: 0,
                  padding: 8,
                  maxHeight: '60vh',
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
              <Button
                size="s"
                mode="tertiary"
                style={{ marginTop: 8 }}
                onClick={copyOutput}
              >
                Скопировать
              </Button>
            </>
          )}
        </Div>
      )}
    </Group>
  );
}
