# 02_SYSTEM_SPECS / 02_bot_vk_facts — Проверка фактов о VK API (задача BOT-0)

> Исполнитель: IDE Execution Agent (Devin). Дата проверки: 2026-10-05.
> Источники: только первоисточники — `dev.vk.com` (официальная документация ВК) и репозитории `github.com/VKCOM/*` (`api-schema-typescript`). Зеркала `vk.com/dev` были недоступны (бот-защита портала), поэтому сверка с ними не проводилась.
> Каждый пункт V1–V11 соответствует строке Приложения V Spec `docs/02_SYSTEM_SPECS/02_bot.md`; V12–V14 добавлены заданием BOT-0.

### V1 — Срок и формат ответа на событие Callback; повторы

- Status: CONFIRMED
- Fact: На каждое уведомление сервер обязан вернуть строку `ok` и HTTP-статус 200. При неудаче ВК повторяет событие с заголовком `X-Retry-Counter` — до 5 повторов с интервалами 10 с, 3 мин, 10 мин, 30 мин, 1 ч. Дополнительно сервер может вернуть `Retry-After` с кодами 410/429/503 (интервал меньше 3 часов, фактическая переотправка может быть позже). Если сервер несколько раз подряд вернёт ошибку, «Callback API временно перестанет отправлять на него уведомления». Ответ строкой `remove` удаляет сервер из списка Callback — отвечать ей нельзя.
- Source: https://dev.vk.com/ru/api/callback/getting-started (разделы «Работа с Callback API», «HTTP-заголовки: X-Retry-Counter, Retry-After», «Удаление сервера»)
- Spec impact: п. 5.1 — дописать в таблицу ответов и примечание: повторы ВК идут по расписанию 10 с → 3 мин → 10 мин → 30 мин → 1 ч (всего 5 попыток), далее — временная приостановка доставки; обработчик никогда не должен отвечать строкой `remove`; поддержанные сервером коды ошибок уже соответствуют (500 → повтор ВК).

### V2 — Событие `confirmation`, поле `secret`, версия Callback API

- Status: CONFIRMED
- Fact: На событие `type = confirmation` сервер возвращает заданную строку подтверждения (plain text, без `ok`). Секретный ключ настраивается в сообществе и приходит в поле `secret` каждого уведомления. Формат обёртки: `{type, event_id, v, object, group_id}`. Callback API поддерживает версии `5.81` и новее; версия задаётся в настройках сервера, методом `groups.setCallbackSettings` (`api_version`) или строкой `version X.Y` в ответе на событие. Строка подтверждения из `groups.getCallbackConfirmationCode` отличается от показанной в веб-интерфейсе и годится только для настройки через API.
- Source: https://dev.vk.com/ru/api/callback/getting-started (разделы «Подключение», «Секретный ключ», «Изменение версии API», «Формат данных»)
- Spec impact: none — поведение п. 5.1 соответствует. Можно зафиксировать полезное замечание: `VK_CALLBACK_CONFIRMATION` надо брать из веб-интерфейса сообщества (а не из `getCallbackConfirmationCode`, если сервер подтверждается через UI).

### V3 — Передача ключа заголовком `Authorization: Bearer`

- Status: CONFIRMED
- Fact: Официальная инструкция требует передавать ключ доступа в каждом запросе заголовком `Authorization: Bearer <КЛЮЧ_ДОСТУПА>`; тело POST — `application/x-www-form-urlencoded` или `multipart/form-data` (`application/json` не поддерживается). Примеры документации используют именно заголовок.
- Source: https://dev.vk.com/ru/api/api-requests (разделы «Синтаксис запросов», «Заголовки»), https://dev.vk.com/ru/api/community-messages/getting-started («Ключ доступа»)
- Spec impact: none — INV-B9 соответствует документации.

### V4 — `peer_ids` с одним получателем: формат ответа

- Status: CONFIRMED
- Fact: Если передан `peer_ids`, `messages.send` возвращает массив объектов (даже для одного получателя) с полями `peer_id` (int), `message_id` (int), `conversation_message_id` (int) и `error`. Поле `error` — объект `BaseMessageError` вида `{code: int, description: string}`: описание ошибки и её код лежат внутри этого объекта, а не в верхнеуровневом `error` ответа API.
- Source: https://dev.vk.com/ru/method/messages.send (раздел «Результат»), https://github.com/VKCOM/api-schema-typescript (`MessagesSendUserIdsResponseItem`, `BaseMessageError`)
- Spec impact: п. 3.3 — уточнить разбор ответа: `response` — массив; брать `response[0]`; успех — наличие `message_id`; ошибка получателя — `response[0].error.code` (объект, не строка). Это важно для классификации 901/902 по п. 2.7.

### V5 — Коды ошибок и лимиты `messages.send` сообщества

- Status: CLARIFIED
- Fact: Коды подтверждены справочником общих ошибок и списком ошибок `messages.send`: 5 — «Авторизация пользователя не удалась», 6 — «Слишком много запросов в секунду», 9 — «Слишком много однотипных действий» (флуд-контроль), 10 — внутренняя ошибка сервера, 15 — «Доступ запрещён», 27 — «Ключ доступа сообщества недействителен», 28 — «Ключ доступа приложения недействителен», 29 — «Достигнут количественный лимит на вызов метода», 100 — неверный параметр, 900 — получатель в чёрном списке, 901 — нет разрешения, 902 — приватность, 911 — невалидная клавиатура, 914 — слишком длинное сообщение. Лимит частоты для ключа сообщества — **20 запросов в секунду**; количественные лимиты на вызовы ВК не раскрывает. Дополнительно найдены коды, релевантные боту: 984 — «You has spam restriction», 1021 — «Can't send messages for users without conversation», 943/944 — ошибки интентов.
- Source: https://dev.vk.com/ru/reference/errors, https://dev.vk.com/ru/method/messages.send («Коды ошибок»), https://dev.vk.com/ru/api/api-requests («Ограничения»)
- Spec impact: п. 2.7 — в класс «ключ недействителен/нет прав → HALTED_AUTH» добавить коды 27 и 28; рассмотреть 1021 как класс «нет разрешения/нет диалога» → `DROPPED / NO_CONSENT` или `BLOCKED`. П. 4.2 — диапазон `sender.max_requests_per_second` сузить до `1–20` (документированный потолок ключа сообщества — 20, старт 15 остаётся корректным). В таблицу ошибок добавить 984 (антиспам) как системный/игроковый сбой на усмотрение Lead AI.

### V6 — Параметр `intent`: значения и необходимость

- Status: CLARIFIED
- Fact: Параметр `intent` необязателен («Строка, описывающая интенты»). Официальная схема фиксирует 12 значений: `account_update`, `bot_ad_invite`, `bot_ad_promo`, `confirmed_notification`, `customer_support`, `default`, `finance_notification`, `game_notification`, `moderated_newsletter`, `non_promo_newsletter`, `promo_newsletter`, `purchase_update`. Существование отдельных лимитов на интент подтверждают ошибки 943 «Cannot use this intent» и 944 «Limits overflow for this intent»; условия применения отдельных значений в доступной документации не опубликованы.
- Source: https://dev.vk.com/ru/method/messages.send (`intent`, ошибки 943/944), https://github.com/VKCOM/api-schema-typescript (`MessagesSendParams.intent`)
- Spec impact: п. 3.3 — параметр необязателен, отправка без `intent` корректна (запасной вариант срабатывает). Рекомендация: оставить без изменений либо добавить `vk.intent` со значением `default` отдельной правкой; `game_notification` подтверждён в перечне, но условия его применения недокументированы — использовать только при явной необходимости.

### V7 — Даёт ли первое сообщение игрока право отвечать; `isMessagesFromGroupAllowed`

- Status: CONFIRMED
- Fact: Да: «Если пользователь написал сообщение сообществу первым, это приравнивается к согласию на получение ответных сообщений (без ограничений по времени, если пользователь не запретил сообщения вручную)». Метод `messages.isMessagesFromGroupAllowed` возвращает объект с единственным полем `is_allowed` (1 — разрешено, 0 — нет). Прямого утверждения «метод вернёт 1 после первого сообщения пользователя» в документации нет, но документированное правило приравнивает такое сообщение к согласию.
- Source: https://dev.vk.com/ru/api/community-messages/getting-started («Работа с сообщениями»), https://dev.vk.com/ru/method/messages.isMessagesFromGroupAllowed
- Spec impact: п. 2.3, 3.7, 3.9 — дизайн не ломается: ответы (`REPLY`) без согласия соответствуют правилу ВК. Уточнение: событие `message_new` можно учитывать как сигнал `ALLOWED` для ответных сообщений, но для `NOTIFICATION` сверка `isMessagesFromGroupAllowed` остаётся арбитром (INV, п. 2.3 сохранить).

### V8 — `VKWebAppAllowMessagesFromGroup`

- Status: CLARIFIED
- Fact: Метод вызывается `bridge.send('VKWebAppAllowMessagesFromGroup', { group_id, key? })`: `group_id` — обязательный `integer`, `key` — необязательная строка для идентификации. Успех: `Promise` → `{ result: true }` (или событие `VKWebAppAllowMessagesFromGroupResult`). Отказ — ошибка `User denied` (событие `VKWebAppAllowMessagesFromGroupFailed`). Доступен на платформе Web (десктоп). Важно: событие «станет доступно пользователям после того, как приложение пройдёт модерацию». Возможность повторного вызова после отказа в документации не описана.
- Source: https://dev.vk.com/ru/bridge/VKWebAppAllowMessagesFromGroup
- Spec impact: п. 5.6 — добавить требование: мини-приложение должно пройти модерацию ВК, иначе вызов не сработает у игроков (организационный пункт для Project Owner). Повторный вызов после отказа — не документирован: текущий поток (молчаливый возврат переключателя + `POST /bot/consent/refresh`) оставить, повторные вызовы не блокировать в коде.

### V9 — Пределы клавиатуры; `open_app` и `location.hash`; совместимость типов

- Status: CLARIFIED
- Fact: Постоянная клавиатура (`inline: false`): до 40 кнопок, до 10 рядов по 5 кнопок; `one_time` работает только при `inline: false`. Инлайн (`inline: true`): до 10 кнопок, до 6 рядов по 5. `label` кнопок `text`/`callback` — до 40 символов; `payload` — JSON-строка до 255 символов, начинается и заканчивается `{}`. Удаление клавиатуры — передача `{ "buttons": [] }`, т.е. панель сохраняется у игрока до явной замены. `open_app`: обязательные `app_id`, `label`; необязательные `owner_id`, `hash` — «будет передан в строке параметров запуска после символа `#`». Прямого утверждения про одновременное сосуществование инлайн- и постоянной клавиатуры в диалоге нет, но правило «клавиатура держится, пока её не заменили/не очистили» позволяет сочетать их в разных сообщениях.
- Source: https://dev.vk.com/ru/api/bots/development/keyboard, https://dev.vk.com/ru/api/bots/development/keyboard/key-types, https://dev.vk.com/ru/api/bots/development/keyboard/enable-keyboard
- Spec impact: п. 4.7 — диапазон `dialog.labels.*` (1–40) подтверждён, оставить. П. 5.5 — клавиатура проекта (3 ряда ≤5 кнопок, `label` ≤ 40, `payload` ≤ 255 с `{}`) укладывается в пределы; `hash` подтверждён как способ навигации. D3 держится: повторная передача постоянной клавиатуры — единственный документированный способ гарантировать её установку; при передаче инлайн-клавиатуры в ответе «Помощь» постоянная панель не снимается (снимается только `{buttons:[]}`).

### V10 — `message_new` при нажатии `text`-кнопки; `payload` кнопки «Начать»

- Status: CONFIRMED
- Fact: Кнопка `text` отправляет сообщение с текстом `label`; `payload` кнопки «приходит серверу бота в событии `message_new` в поле `payload`». При включённой в сообществе кнопке «Начать» первое сообщение пользователя несёт `payload` вида `{"command":"start"}`. Документация предупреждает: `payload` надо проверять на сервере — пользователь может подменить его вручную.
- Source: https://dev.vk.com/ru/api/bots/development/keyboard («Особенности работы»), https://dev.vk.com/ru/api/bots/development/keyboard/key-types (`text`), https://dev.vk.com/ru/api/bots/development/keyboard/enable-keyboard (кнопка «Начать»)
- Spec impact: п. 3.9 — чтение команды из `payload` корректно (`{"cmd":"status"|"help"}` + распознавание `{"command":"start"}` от кнопки «Начать»); распознавание по тексту оставить как запасной путь. Включаемость «Начать» — настройка в веб-интерфейсе сообщества (для чек-листа Project Owner).

### V11 — Несколько сообщений одному получателю подряд; антиспам

- Status: CLARIFIED
- Fact: Документированного запрета или интервала на несколько сообщений одному получателю нет; единственные числовые лимиты — 20 запросов/с на ключ сообщества и ≤100 получателей на вызов. Антиспам реализован на стороне ВК непрозрачно: количественные лимиты «не предоставляются», их превышение даёт ошибку 29; общий флуд-контроль — ошибка 9; есть код 984 «You has spam restriction». Отправка пользователям без существующего диалога может дать ошибку 1021.
- Source: https://dev.vk.com/ru/api/api-requests («Ограничения»), https://dev.vk.com/ru/method/messages.send («Коды ошибок»), https://dev.vk.com/ru/api/bots/development/messages
- Spec impact: п. 3.4 — внутренние ограничители (`max_per_window`, `daily_cap_normal`) остаются актуальными и достаточными; обработку ошибок 9 и 984 по игроку и 1021 добавить в таблицу п. 2.7 (см. V5).

### V12 — Канонический хост API: `api.vk.com` vs `api.vk.ru`

- Status: CLARIFIED
- Fact: Текущая документация предписывает `api.vk.ru`: «В каждом запросе необходимо указать доменное имя сервера VK API: `api.vk.ru`», и все примеры (cURL, PHP) используют `https://api.vk.ru/method/…`. Явного уведомления о выводе `api.vk.com` из эксплуатации в доступной документации нет; исторический домен в примерах не встречается.
- Source: https://dev.vk.com/ru/api/api-requests («Адрес сервера», «Примеры»), https://dev.vk.com/ru/api/callback/getting-started (пример PHP)
- Spec impact: п. 4.1 — `vk.api_base_url` стартовое значение заменить с `https://api.vk.com/method` на `https://api.vk.ru/method` (затронутый ключ конфига: `vk.api_base_url`).

### V13 — Актуальная версия API; существование `5.199`

- Status: CONFIRMED
- Fact: Версия `5.199` существует — это самая свежая запись на странице версий («Изменения во внутренних алгоритмах обработки некоторых запросов. Изменений в составе API-методов, их параметров и возвращаемых значений нет»). Устаревшей она не помечена; Callback API поддерживает версии от `5.81`. (Текст страницы «Формат запросов» устарел и называет актуальной `5.131` — на список версий это не влияет.)
- Source: https://dev.vk.com/ru/reference/versions, https://dev.vk.com/ru/api/callback/getting-started («Изменение версии API»)
- Spec impact: none — `vk.api_version = 5.199` в п. 4.1 остаётся валидным.

### V14 — `messages.send` + `peer_ids`: точная форма ответа и дедупликация `random_id`

- Status: CONFIRMED
- Fact: При `peer_ids` ответ — массив объектов `{peer_id, message_id, conversation_message_id, error}`; `error` — объект `{code, description}` (`BaseMessageError`), т.е. код ошибки получателя лежит в `response[i].error.code`. Успех для единственного получателя — `response[0].message_id` без `error`. Дедупликация `random_id` — **на диалог** (в привязке к приложению и отправителю): проверка уникальности выполняется «в заданном диалоге за последний час (но не более 100 последних сообщений)»; `random_id=0` отключает проверку.
- Source: https://dev.vk.com/ru/method/messages.send (`random_id`, «Результат»), https://github.com/VKCOM/api-schema-typescript (`MessagesSendUserIdsResponseItem`, `BaseMessageError`)
- Spec impact: п. 3.3 — разбор ответа уточнить, как в V4. INV-B6 и схема повторов подтверждены: повторная отправка с тем же `random_id` безопасна в пределах часа; задержки больше часа защищает `expires_at`/UNIQUE в очереди. Строку «`random_id` — случайное 31-битное число» оставить (int32 ≥ 1).

## Сводка влияния на Spec

| № | Status | Spec раздел | Предлагаемая правка |
| :-- | :-- | :-- | :-- |
| V1 | CONFIRMED | п. 5.1 | Дописать расписание повторов ВК (10с/3м/10м/30м/1ч, ≤5) и запрет ответа `remove`; дизайн не меняется |
| V4 | CONFIRMED | п. 3.3 | Разбор ответа: `response[0].error.code` — объект `{code, description}`, успех = `response[0].message_id` |
| V5 | CLARIFIED | п. 2.7, п. 4.2 | Добавить 27 и 28 в класс `HALTED_AUTH`; добавить 984 и 1021 в таблицу реакций; `sender.max_requests_per_second` диапазон → `1–20` |
| V6 | CLARIFIED | п. 3.3 | `intent` не передавать (запасной вариант); при желании — отдельная правка `vk.intent = default` |
| V7 | CONFIRMED | п. 2.3, 3.9 | Дизайн не меняется; `message_new` можно учитывать как сигнал разрешения для ответов |
| V8 | CLARIFIED | п. 5.6 | Добавить требование «мини-приложение должно пройти модерацию»; повторный вызов после отказа недокументирован — не блокировать |
| V9 | CLARIFIED | п. 5.5, 4.7 | Пределы подтверждены и уже учтены; зафиксировать, что постоянная клавиатура снимается только `{buttons:[]}` и может сосуществовать с инлайн-сообщением |
| V11 | CLARIFIED | п. 3.4, 2.7 | Внутренние лимиты сохранить; учесть ошибки 9/984/1021 (см. V5) |
| V12 | CLARIFIED | п. 4.1 | `vk.api_base_url` → `https://api.vk.ru/method` |

CONFIRMED без правок Spec: V2, V3, V10, V13, V14 (V14/V4 уточняют разбор ответа — отражены в строках V4/V14 выше).
