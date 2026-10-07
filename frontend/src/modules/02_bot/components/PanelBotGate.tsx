/**
 * PanelBotGate — «Подключите штабной терминал» (Spec 5.6).
 *
 * Shown INSTEAD of the registration form when the server requires
 * message consent. The only way forward is the plain anchor to
 * `chat_url` — it opens the chat in a new tab (target=_blank,
 * rel="noopener noreferrer"), the app stays open and starts polling
 * POST /bot/consent/refresh at the server-given interval. On ALLOWED
 * the gate disappears by itself; on timeout the «Проверить ещё раз»
 * button fires one manual refresh and the chat link keeps working
 * (clicking it restarts the polling). No VK Bridge calls, no automatic
 * navigation, no browser storage.
 */

import {
  Button,
  Div,
  Group,
  PanelHeader,
  Spinner,
  Text,
} from '@vkontakte/vkui';

import {
  useConsentPolling,
  type ConsentPolling,
} from '../hooks/useConsentPolling';
import type { BotStatusDTO, ReadyBotStatusDTO } from '../api';
import { BOT_TEXTS } from '../texts';

export interface PanelBotGateProps {
  dto: ReadyBotStatusDTO;
  /** Fresh status after consent became ALLOWED — the gate closes. */
  onAllowed: (dto: BotStatusDTO) => void;
  /** A refresh answered 409 BOT_DISABLED — behave as bot off. */
  onDisabled: () => void;
}

export function PanelBotGate({ dto, onAllowed, onDisabled }: PanelBotGateProps) {
  const polling: ConsentPolling = useConsentPolling({
    intervalSeconds: dto.consent_poll_interval_seconds,
    timeoutSeconds: dto.consent_poll_timeout_seconds,
    onAllowed,
    onDisabled,
  });

  return (
    <>
      <PanelHeader>{BOT_TEXTS.gateTitle}</PanelHeader>
      <Group>
        <Div>
          <Text>{BOT_TEXTS.gateText}</Text>
        </Div>
        <Div>
          <Button
            size="l"
            stretched
            href={dto.chat_url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => polling.start()}
          >
            {BOT_TEXTS.gateButton}
          </Button>
        </Div>
        {polling.state === 'polling' && (
          <Div
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            data-testid="bot-gate-waiting"
          >
            <Spinner size="s" />
            <Text>{BOT_TEXTS.gateWaiting}</Text>
          </Div>
        )}
        {polling.state === 'timed_out' && (
          <>
            <Div>
              <Text>{BOT_TEXTS.gateTimeout}</Text>
            </Div>
            <Div>
              <Button
                size="l"
                stretched
                mode="secondary"
                onClick={polling.checkOnce}
              >
                {BOT_TEXTS.recheckButton}
              </Button>
            </Div>
          </>
        )}
      </Group>
    </>
  );
}
