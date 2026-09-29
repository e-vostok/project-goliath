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

## Границы затрагиваемых директорий

- backend/src/core/admin/ — новое: security.py, registry.py, router.py
- backend/src/modules/_00_core/ — правка: hook-функции reset/state_view + регистрация в lifespan
- backend/tests/core/admin/ — новое
- .env в корне репозитория (gitignored): ADMIN_VK_USER_IDS

## Issues

- [x] **Issue 1: Admin auth + Registry infrastructure** — `require_admin` поверх
  `get_current_player`, проверка по списку `ADMIN_VK_USER_IDS`; класс `AdminRegistry`
  (register_reset/register_state_view/clear); без изменений схемы БД.
- [ ] **Issue 2: Admin endpoints + hooks для 00_core** — `POST /admin/tick/run`,
  `GET /admin/tick-log`, `GET /admin/state`, `POST /admin/state/reset`; reset()/state_view()
  для 00_core (nations/provinces/scheduled_actions/game_clock — players не трогаем).
- [ ] **Issue 3: Блок «Админ» в существующем UI (JSON)** — GET /admin/me (200 {"is_admin": true} / 403 ADMIN_REQUIRED); в панели государства блок «Админ», виден только админу: «Запустить ход», «Сбросить мир» (модалка подтверждения), «Состояние», «Журнал ходов»; вывод — форматированный JSON-текст; без нового экрана/роута.

## Backlog & Tech Debt

- Reset не трогает players — обсудить, нужен ли отдельный флаг «полный сброс».
- Красивые таблицы вместо JSON — позже.
- Ручной тик и планировщик не защищены общим локом; reset не чистит tick_log и игроков.
