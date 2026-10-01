# 03_ROADMAP / admin_panel

## Статус

Служебный технический функционал (не игровой модуль в терминах Full-Stack Vertical Slices —
не проходит все 5 онтологических критериев, поэтому не имеет Game Bible и System Spec).

## Архитектурная цель

Прямой контроль над тестовым циклом без ожидания суточного тика: ручной запуск хода,
просмотр состояния/tick_log, сброс состояния до дефолтов — через защищённые (только для
админа) JSON-эндпоинты, без экранов VKUI. Расширяемость для будущих модулей — через реестр
хуков (AdminRegistry) по аналогии с TickOrchestrator: новый модуль регистрирует свой
reset/state-hook одной строкой, без переделки панели.

Формат вывода: все времена в admin-ответах — строки `YYYY-MM-DD HH:MM:SS` в игровой
зоне `tick.tick_timezone` под обычными именами полей; в БД хранится UTC.

## Границы затрагиваемых директорий

- backend/src/core/admin/ — новое: security.py, registry.py, router.py
- backend/src/modules/_00_core/ — правка: hook-функции reset/state_view + регистрация в lifespan
- backend/tests/core/admin/ — новое
- .env в корне репозитория (gitignored): ADMIN_VK_USER_IDS

## Issues

- [x] **Issue 1: Admin auth + Registry infrastructure** — `require_admin` поверх
  `get_current_player`, проверка по списку `ADMIN_VK_USER_IDS`; класс `AdminRegistry`
  (register_reset/register_state_view/clear); без изменений схемы БД.
- [x] **Issue 2: Admin endpoints + hooks для 00_core** — `POST /admin/tick/run`,
  `GET /admin/tick-log`, `GET /admin/state`, `POST /admin/state/reset`; reset()/state_view()
  для 00_core (nations/provinces/scheduled_actions/game_clock — players не трогаем).
- [x] **Issue 3: Блок «Админ» в существующем UI (JSON)** — GET /admin/me (200 {"is_admin": true} / 403 ADMIN_REQUIRED); в панели государства блок «Админ», виден только админу: «Запустить ход», «Сбросить мир» (модалка подтверждения), «Состояние», «Журнал ходов»; вывод — форматированный JSON-текст; без нового экрана/роута.
- [x] **Issue 4: Reset чистит tick_log + полноэкранный просмотр JSON** — reset-hook
  00_core удаляет журнал ходов; «Развернуть» открывает оверлей на весь экран с
  «Скопировать» / «Закрыть» / Esc.
- [x] **Issue 5: Тулбар над JSON + время в игровой зоне** — «Скопировать» и
  «Развернуть» перенесены в тулбар над `<pre>` (видны без прокрутки, max-height 40vh);
  бэкенд-часть (`*_local`-поля рядом с UTC) заменена в Issue 6.
- [x] **Issue 6: Admin output — московское время, простой формат** — все datetime-поля
  в admin-ответах (state view, `GET /admin/tick-log`, `POST /admin/tick/run`) отдаются
  как `YYYY-MM-DD HH:MM:SS` в `tick.tick_timezone` под исходными именами; `*_local`-ключи
  удалены; общий helper `format_game_time` в `modules/_00_core/tick_schedule.py`;
  хранение и планировщик остаются в tz-aware UTC.

## Backlog & Tech Debt

- Reset не трогает players — обсудить, нужен ли отдельный флаг «полный сброс».
- Свежая БД: миграция 0001 сеет первый `next_tick_at` как `now + tick_interval_hours`; привести её к `next_tick_after()` (фиксированное локальное время), затем удалить `tick_interval_hours`. Ручной тик и reset уже используют `next_tick_after()` и не сдвигают суточное расписание.
- Красивые таблицы вместо JSON — позже.
- Ручной тик и планировщик не защищены общим локом; reset не чистит игроков.
