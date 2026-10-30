/**
 * errors.ru.ts — the Russian dictionary of server `ErrorResponse.code`
 * values (UI Spec 7, version 0.9.0 unit 9). One object per language:
 * `errorText` reads the table through a single `const messages =
 * ERRORS_RU` line, so a second language later is a new file plus that
 * one line — no locale switching exists yet.
 *
 * The nation field codes are NOT here — `nationErrorTexts.ts` owns them
 * (its texts need the limits from GET /nations/rules). `SERVER_RU`
 * marks the codes whose server `detail` is already Russian by contract
 * (Spec 04_orders 5.3) and carries the concrete reason — for them
 * `errorText` returns the detail itself.
 */

/** «The server detail is already Russian by contract» marker. */
export const SERVER_RU: unique symbol = Symbol('SERVER_RU');

/** 5xx without a table entry. */
export const SERVER_ERROR_RU = 'Ошибка сервера — попробуйте ещё раз позже.';

/** A code nothing covers. */
export const fallbackErrorRu = (code: string): string =>
  `Не удалось выполнить действие. Код ошибки: ${code}.`;

export const ERRORS_RU: Record<string, string | typeof SERVER_RU> = {
  /* Session — the player re-opens the app, the code is not explained. */
  INVALID_SIGNATURE: 'Сессия устарела — откройте приложение заново.',
  TIMESTAMP_EXPIRED: 'Сессия устарела — откройте приложение заново.',
  UNAUTHORIZED: 'Сессия устарела — откройте приложение заново.',

  /* Bot / consent. */
  CONSENT_REQUIRED: 'Нужно разрешить сообщения от сообщества.',
  BOT_DISABLED: 'Рассылка сообщений сейчас отключена.',

  /* Provinces and the starting group. */
  PROVINCE_TAKEN:
    'Одна из провинций уже занята другим государством. Выберите другие.',
  PROVINCE_NOT_FOUND: 'Такой провинции нет.',
  PROVINCE_COUNT_OUT_OF_RANGE: 'Число выбранных провинций не подходит.',
  PROVINCE_NOT_LAND: 'Выбрать можно только сухопутные провинции.',
  STARTING_GROUP_NOT_CONNECTED:
    'Выбранные провинции должны быть связаны между собой.',

  /* Nation. */
  NATION_ALREADY_EXISTS: 'У вас уже есть государство.',
  NATION_NOT_FOUND: 'Государство не найдено.',
  /* PATCH /admin/nations/{id} with an empty body (0.11.0 unit 8b). */
  NOTHING_TO_CHANGE: 'Нечего сохранять — поля не изменились.',
  /* The nation's uploaded picture was already removed (0.12.0 u9). */
  IMAGE_NOT_FOUND: 'Картинки уже нет.',

  /* Player, clock, map, registry. */
  PLAYER_NOT_FOUND: 'Игрок не найден.',
  GAME_CLOCK_NOT_FOUND: 'Игровые часы ещё не запущены.',
  TURN_OUT_OF_RANGE: 'Такого хода нет.',
  MAP_VERSION_UNKNOWN: 'Карта обновилась — обновите страницу.',
  REGISTRY_TABLE_NOT_FOUND: 'Такой таблицы нет.',
  REGISTRY_PROVIDER_FAILED:
    'Не удалось собрать таблицу. Попробуйте ещё раз позже.',

  /* Orders and verdicts. */
  ORDER_NATION_REQUIRED: 'Подать приказ может только владелец государства.',
  ORDER_AUTHOR_LIMIT_REACHED:
    'Достигнут предел: дождитесь вердикта по одному из ваших приказов.',
  ORDER_NOT_FOUND: 'Приказ не найден.',
  ORDER_VERDICT_FORBIDDEN: 'Вердикт по этому приказу писать нельзя.',
  ORDER_VERDICT_EXISTS: 'По этому приказу вердикт уже записан.',
  ORDER_NUMBER_CONFLICT:
    'Не удалось присвоить приказу номер — отправьте приказ ещё раз.',
  ORDER_TITLE_INVALID: SERVER_RU,
  ORDER_SUMMARY_INVALID: SERVER_RU,
  ORDER_URL_INVALID: SERVER_RU,
  /* Admin judge assignment (0.11.0 unit 10b) — the preview's blocker
     codes, also the POST /admin/orders/{n}/judge refusals. */
  ORDER_ALREADY_DECIDED:
    'По приказу уже вынесен вердикт — судью менять нельзя.',
  JUDGE_IS_AUTHOR: 'Автор приказа не может быть его судьёй',
  ALREADY_JUDGE: 'Этот игрок уже назначен судьёй этого приказа.',

  /* Map maintenance — transient states the player cannot act on. */
  RETIRED_PROVINCE_OWNED: 'Действие сейчас недоступно. Попробуйте позже.',
  RETIRED_PROVINCE_HISTORY: 'Действие сейчас недоступно. Попробуйте позже.',
  FREQUENCY_CAP_EXCEEDED: 'Действие сейчас недоступно. Попробуйте позже.',

  /* Administrator-only codes — a regular player never triggers them. */
  ADMIN_REQUIRED: 'Действие доступно только администратору.',
  RESET_DISABLED: 'Сброс состояния сейчас отключён.',
  CONFIRM_REQUIRED: 'Действие нужно подтвердить.',
  MODULE_NOT_FOUND: 'Такого раздела нет.',
  TICK_IN_PROGRESS: 'Ход уже считается — попробуйте через минуту.',
  CONFIRMATION_MISMATCH: 'Подтверждение не совпало — проверьте ввод.',
  CANNOT_DELETE_SELF: 'Удалить самого себя нельзя.',
  CANNOT_DELETE_ADMIN: 'Удалить администратора нельзя.',

  /* Province transfer — the panel's «Провинции» (0.11.0 unit 9b). */
  ALREADY_OWNER: 'Провинция уже принадлежит этому государству.',
  SEIZE_NOT_CONFIRMED:
    'Подтвердите изъятие провинции у другого государства.',
  LAST_PROVINCE:
    'Это последняя провинция государства. Вывести или передать её ' +
    'нельзя: государство без провинций не бывает. Если государство ' +
    'больше не нужно, удалите его целиком в разделе «Государства».',
  CAPITAL_REQUIRED:
    'Провинция — столица государства: выберите новую столицу из ' +
    'оставшихся провинций.',
  PROVINCE_NAME_UNKNOWN:
    'У выбранной провинции нет названия — назначить её столицей нельзя.',
};
