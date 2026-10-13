/**
 * BotConsentRow — the «Уведомления» line on the nation screen (Spec 5.6).
 *
 * ALLOWED → «Включены». DENIED / UNKNOWN → «Выключены» plus the
 * «Включить в чате» link (chat_url, new tab) that starts the same
 * consent polling as the gate; while polling a «Ждём подтверждения от
 * ВК…» hint shows, on timeout — «Проверить ещё раз».
 *
 * The row is hidden entirely when the bot is disabled, the status
 * request failed, or the status is stale with consent UNKNOWN
 * (fail-open, INV-B15). Existing owners are never pushed through the
 * consent gate — this row is all they see.
 */

import { Button, Div, Link, SimpleCell, Spinner, Text } from '@vkontakte/vkui';

import { useBotStatus } from '../hooks/useBotStatus';
import { useConsentPolling } from '../hooks/useConsentPolling';
import { BOT_TEXTS } from '../texts';

export function BotConsentRow() {
  const bot = useBotStatus();
  const dto = bot.state.status === 'ready' ? bot.state.dto : null;

  const polling = useConsentPolling({
    // dto === null never reaches the UI — the row is hidden, so these
    // zeroes only satisfy the hook signature.
    intervalSeconds: dto?.consent_poll_interval_seconds ?? 0,
    timeoutSeconds: dto?.consent_poll_timeout_seconds ?? 0,
    onAllowed: (fresh) => bot.update(fresh),
    onDisabled: () => {
      if (bot.state.status === 'ready') {
        bot.update({ ...bot.state.dto, enabled: false });
      }
    },
  });

  if (dto === null || (dto.stale && dto.consent === 'UNKNOWN')) {
    return null;
  }

  const allowed = dto.consent === 'ALLOWED';

  return (
    <>
      <SimpleCell
        disabled
        subtitle={BOT_TEXTS.rowLabel}
        after={
          !allowed ? (
            <Link
              href={dto.chat_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => polling.start()}
            >
              {BOT_TEXTS.rowEnable}
            </Link>
          ) : undefined
        }
      >
        {allowed ? BOT_TEXTS.rowOn : BOT_TEXTS.rowOff}
      </SimpleCell>
      {!allowed && polling.state === 'polling' && (
        <Div
          style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          data-testid="bot-row-waiting"
        >
          <Spinner size="s" />
          <Text>{BOT_TEXTS.gateWaiting}</Text>
        </Div>
      )}
      {!allowed && polling.state === 'timed_out' && (
        <Div>
          <Button size="s" mode="secondary" onClick={polling.checkOnce}>
            {BOT_TEXTS.recheckButton}
          </Button>
        </Div>
      )}
    </>
  );
}
