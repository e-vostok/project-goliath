/**
 * All user-visible strings of module 02_bot, in one place (Spec 5.6).
 * Numbers and addresses are NOT here — they arrive in GET /bot/status.
 */
export const BOT_TEXTS = {
  gateTitle: 'Подключите штабной терминал',
  gateText:
    'Чтобы получать сводки хода и тревоги, нужно разрешить сообщения от сообщества. ' +
    'Нажмите «Авторизоваться в боте», в открывшемся чате нажмите «Начать» ' +
    'и вернитесь сюда: регистрация откроется сама.',
  gateButton: 'Авторизоваться в боте',
  gateWaiting: 'Ждём подтверждения от ВК…',
  gateTimeout:
    'Подтверждение не пришло. Убедитесь, что в чате нажата «Начать», ' +
    'и проверьте ещё раз.',
  recheckButton: 'Проверить ещё раз',
  rowLabel: 'Уведомления',
  rowOn: 'Включены',
  rowOff: 'Выключены',
  rowHint: 'Уведомления выключены',
  rowEnable: 'Включить в чате',
} as const;
