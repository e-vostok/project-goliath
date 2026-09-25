# 03_ROADMAP / 00_core

## Архитектурная цель модуля

Заложить фундамент проекта: идентификация игрока через VK (без пароля),
доменные сущности `Player` / `Nation` / `Province`, универсальный примитив
«механический деятельный акт» (`ScheduledAction`), Tick DAG-оркестратор
с точкой расширения для будущих модулей-сателлитов, собственный игровой
календарь. По завершении модуля игрок может: открыть клиент, автоматически
зарегистрироваться, создать/отредактировать/удалить государство, и увидеть,
как срабатывает ход (даже без единого подключённого модуля-сателлита —
тик просто не находит зарегистрированных обработчиков фаз и сразу переходит
к `finalize_tick()`).

## Границы затрагиваемых директорий

- `backend/src/core/` — новое: `db.py`, `security/jwt.py`, `security/vk_signature.py`, `tick/orchestrator.py`, `config/loader.py`
- `backend/src/modules/00_core/` — новое: `models.py`, `service.py`, `tick_handler.py`, `router.py`, `schemas.py`, `config_schema.py`
- `backend/tests/fixtures/` — новое: фабрики `Player`, `Nation`, `Province`
- `backend/tests/modules/00_core/` — новое
- `configs/00_core.yaml` — уже создан (Шаг 2)
- `frontend/src/shared/` — новое: базовый API-клиент, типы токена/ошибок
- `frontend/src/app/` — правка: интеграция auth-gate в `AppShell`
- `frontend/src/modules/00_core/` — новое: `components/`, `hooks/`, `types.ts`

## Issues

- [ ] **Issue 1: Data Layer & Config-Safe** — Модели SQLAlchemy (`Player`, `Nation`, `Province`, `ScheduledAction`, `GameClock`, `TickLog`) в `backend/src/modules/00_core/models.py`; Alembic-миграция начальной схемы; сид-скрипт таблицы `provinces` (временный плейсхолдер `id=1..100`, `nation_id=NULL` — см. открытый вопрос выше); `config_schema.py` (готов с Шага 2) подключён к загрузке при старте `main.py`; тест `test_configs_validity.py`. **Результат:** полный набор корневых таблиц ядра существует в БД, баланс валидируется до старта сервера, констрейнты `UNIQUE(owner_player_id)` / `UNIQUE(name)` / `UNIQUE(color_hex)` подтверждены тестом на реальной тестовой БД (INV-1, INV-2).

- [ ] **Issue 2: Domain Simulation & Tick DAG** — `PlayerService` (get-or-create по `vk_user_id`); `NationService` (атомарные create/update/delete с проверкой уникальности и резервированием провинций, INV-3, INV-6); `ScheduledActionService` (постановка в очередь + алгоритм проверки частоты из Части 3 Спека); `TickOrchestrator` в `backend/src/core/tick/orchestrator.py` — генерик-раннер по перечислению `TickPhase`, точка регистрации обработчиков для будущих модулей, `finalize_tick()` (инкремент `current_turn`, пересчёт календаря, запись `tick_log` вне основной транзакции — INV-TICK-ATOMICITY). **Результат:** доменная логика государства и очереди действий работает и покрыта тестами на реальной БД без моков; тик-движок проходит полный цикл (даже без единого зарегистрированного модуля-фазы) и корректно откатывается при симулированном исключении в обработчике.

- [ ] **Issue 3: API & DTO** — Роуты `POST /api/v1/auth/vk`, `GET /api/v1/players/me`, `GET/POST/PATCH/DELETE /api/v1/nations`, `GET /api/v1/provinces`, `GET /api/v1/game-clock`; DTO-схемы из Части 5 Спека; Bearer-JWT авторизационный dependency; маппинг доменных ошибок на `ErrorResponse.code` (`NAME_TAKEN`, `PROVINCE_TAKEN` и т.д.). **Результат:** полный REST-контракт ядра доступен и покрыт интеграционными тестами через `httpx.AsyncClient` против реальной тестовой БД, включая проверку кодов ошибок на каждое граничное состояние из Спека.

- [ ] **Issue 4: Client UI / VKUI** — Auth-gate (`ScreenSpinner` на время резолва `/auth/vk`) в `AppShell`; `PanelCreateNation`, `PanelNationHome`, `ModalConfirmDeleteNation` в `frontend/src/modules/00_core/components/`; хуки вызова API (`useAuth`, `useNation`, `useProvinces`) с обработкой состояний загрузки/ошибок и инлайн-маппингом `ErrorResponse.code` на конкретный `FormItem`; вызовы `@vkontakte/vk-bridge` (`VKWebAppInit`, `VKWebAppTapticImpactOccurred`); базовый API-клиент в `frontend/src/shared/`. **Результат:** игрок может пройти полный цикл создания/просмотра/редактирования/удаления государства через интерфейс VKUI на десктопе, с корректной обработкой всех серверных ошибок и тактильным откликом.

- [ ] **Issue 5: Integration / E2E** — Сквозной тест без моков (Anti-Mock Guard): регистрация игрока → создание государства через реальный API-вызов → запись в БД → прогон полного цикла тика через `TickOrchestrator` → верификация итогового состояния (`current_turn` увеличен, `tick_log.status = COMPLETED`); отдельный сценарий отказа (исключение в фазе → откат, `current_turn` не изменился, `scheduled_actions` остались `PENDING`); интеграционный тест `PanelCreateNation` (React Testing Library) на реальный вызов API-клиента и корректный рендер серверных ошибок. **Результат:** подтверждена сквозная целостность модуля от клика в интерфейсе до записи в БД и обратно, без единого мока состояния.

## Backlog & Tech Debt

- Сид провинций (Issue 1) — временный плейсхолдер на 100 ID; требует пересмотра при появлении модуля карты/геовизуализации.
- Полноценный e2e через браузерную автоматизацию (Playwright, реальный клик по кнопкам в реальном браузере) — сейчас Issue 5 покрывает сквозной сценарий на уровне API+БД+тик и точечный RTL-тест панели, не полный браузерный прогон. Рассмотреть отдельным треком после MVP.
- Уведомления через VK-бота о начале/окончании хода — явно out-of-scope в Bible, зона ответственности будущего модуля.
