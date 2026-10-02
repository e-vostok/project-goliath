## 5. Универсальный инструментарий промптов (Zero-Shot Toolkit v2.0)

---

### ПРОМПТ 0: Инициализация сессии модуля в новом чате (Старт)

```markdown
РОЛЬ: Главный системный архитектор и ведущий full-stack разработчик (Principal Systems Architect & Lead Full-Stack Engineer).
ПРОЕКТ: Goliath (Пошаговая асинхронная 4X-стратегия / VK Mini App на React + FastAPI).

КОНТЕКСТ:
Мы начинаем изолированную сессию проектирования и курирования разработки конкретного игрового модуля.
Подключенный к проекту GitHub-репозиторий является единственным источником истины о кодовой базе.

КОНТЕКСТ МОДУЛЯ:
- Целевой модуль: [module_slug, например: economy / military / buildings]
- Зависимости модуля: [Список имен модулей, например: 00_core, economy]

АРХИТЕКТУРНЫЙ СТАНДАРТ:
1. Full-Stack Vertical Slice: каждый модуль охватывает серверную логику, валидацию баланса, место в Tick DAG и клиентский UI на базе @vkontakte/vkui.
2. Config-Safe Pattern: все числовые параметры строго валидируются через Pydantic-схемы.
3. Rule of Read-Only Dependency: запрещены прямые мутации чужих таблиц в БД; связи между модулями-сателлитами строятся только через публичные сервисы или корневые сущности 00_core.
4. Anti-Mock Guard: тесты обязаны выполняться на реальном состоянии тестовой БД с использованием фабрик фикстур. Поверхностные моки запрещены.

ЗАДАЧА:
1. Изучите репозиторий: ознакомьтесь с актуальными версиями development_workflow.md, technical_blueprint.md и спецификациями модулей-зависимостей.
2. Проверьте состояние реестра Tick DAG и сущностей ядра в модуле 00_core.
3. Подтвердите готовность вести модуль по сквозному пайплайну и ожидайте моих вводных данных для Шага 1 (концепт механики для Game Bible) либо Шагов 2–4.
```

---

### ПРОМПТ 1: Концептуализация модуля Game Bible (Шаг 1)

```markdown
РОЛЬ: Ведущий системный геймдизайнер (Lead Systems Game Designer).
ПРОЕКТ: Goliath.

ЗАДАЧА:
Проанализировать сырой концепт механики, проверить границы модульности и сформировать официальный текст правил для файла docs/01_GAME_BIBLE/[module_slug].md.

ВХОДНЫЕ ДАННЫЕ:
<КОНЦЕПТ>
[Опишите задумку своими словами: пользовательский опыт, сценарии действий в VK Mini App, ожидаемый результат]
</КОНЦЕПТ>

ШАГ 1: АРХИТЕКТУРНАЯ ОЦЕНКА ПО 5 ОНТОЛОГИЧЕСКИМ КРИТЕРИЯМ:
1. Суверенность данных: Требуются ли механике собственные таблицы в БД, не принадлежащие другим системам?
2. Фаза в Tick DAG: Имеет ли механика собственный шаг расчета при смене хода и в какую из 5 фаз тика (Environment, Production, Consumption, Resolve, Expiration) она встраивается?
3. Изоляция и валидация баланса: Можно ли вынести все балансовые числа в конфиг и описать их валидационными диапазонами?
4. Пользовательская проекция (UI Presence): Какой интерфейсный экран, модальное окно или элемент управления в VKUI получает игрок?
5. Вес вертикального среза: Раскладывается ли реализация механики (БД + Логика/Тик + API + VKUI + e2e-тест) в диапазон от 3 до 6 атомарных задач?

ШАГ 2: ПРАВИЛА ФОРМАЛИЗАЦИИ ТЕКСТА:
1. Стиль: Сухой, юридически точный язык системного геймдизайна. Никакой художественной воды.
2. Абстракция чисел: Запрещено использовать точные балансные константы. Используйте системные дескрипторы: «базовая стоимость», «коэффициент амортизации», «порог лояльности».
3. Шаблон механики: Триггер -> Условие -> Системный эффект.
4. Описание интерфейса: Четко зафиксируйте, какие экраны/панели видит игрок в клиенте VK Mini App, какие данные получает и к чему приводит осознанное бездействие (пропуск хода).
5. Граничные состояния: Поведение при нулевом балансе, переполнении лимитов, отсутствии связи с сервером.

ВЫХОДНЫЕ ДАННЫЕ:
- Архитектурное решение: [НОВЫЙ_МОДУЛЬ: module_slug | РАСШИРЕНИЕ_СУЩЕСТВУЮЩЕГО: module_slug]
- Готовый Markdown-текст для docs/01_GAME_BIBLE/[module_slug].md с метаданными в шапке (front-matter):
  `module`, `dependencies`, `tick_phase`, `in_scope`, `out_of_scope`.
```

---

### ПРОМПТ 2: Генерация спецификации, конфигурации и схемы валидации (Шаг 2)

```markdown
РОЛЬ: Главный системный архитектор и математический балансер (Principal Systems Architect & Mathematical Balancer).
ПРОЕКТ: Goliath.

ЗАДАЧА:
Преобразовать текст Библии модуля docs/01_GAME_BIBLE/[module_slug].md в полный технический контракт системы, состоящий из трех неразрывных артефактов.

ВХОДНЫЕ ДАННЫЕ:
<ТЕКСТ_БИБЛИИ_МОДУЛЯ>
[Вставьте утвержденный текст из docs/01_GAME_BIBLE/[module_slug].md]
</ТЕКСТ_БИБЛИИ_МОДУЛЯ>

ТРЕБОВАНИЯ К ВЫХОДНЫМ АРТЕФАКТАМ:

ВЫВОД 1: Спек-файл `docs/02_SYSTEM_SPECS/[module_slug].md`
Документ обязан содержать 5 структурированных разделов:
- ЧАСТЬ 1: ДОМЕННАЯ МОДЕЛЬ (Имена сущностей, типы полей, первичные ключи. ПРАВИЛО: внешние ключи разрешены ТОЛЬКО к таблицам 00_core. Прямые связи к другим модулям-сателлитам запрещены).
- ЧАСТЬ 2: ИНВАРИАНТЫ, FSM И МЕСТО В TICK DAG (Бизнес-правила, диаграмма состояний FSM, точная регистрация обработчика в глобальном перечислении TickPhase и список входящих/исходящих фазовых зависимостей).
- ЧАСТЬ 3: МАТЕМАТИЧЕСКИЙ АППАРАТ (Все формулы и алгоритмы расчета тика в формате LaTeX ($$ ... $$) с защитой от деления на ноль, правилами округления и граничными лимитами).
- ЧАСТЬ 4: СПЕЦИФИКАЦИЯ КОНФИГУРАЦИИ (Список всех балансовых ключей, их типы, единицы измерения и допустимые диапазоны: min/max).
- ЧАСТЬ 5: СЕТЕВОЙ И UI КОНТРАКТ (FastAPI эндпоинты, DTO схемы запросов/ответов, спецификация панелей VKUI, компонентов и событий vk-bridge).

ВЫВОД 2: Файл баланса `configs/[module_slug].yaml`
- Валидный YAML со стартовыми числовыми значениями для всех параметров из Части 4.

ВЫВОД 3: Pydantic-схема валидации конфига `backend/src/modules/[module_slug]/config_schema.py`
- Python-код Pydantic-модели с жесткой типизацией и валидаторами (`Field(ge=..., le=...)`), гарантирующий отлов некорректного баланса до старта сервера.
```

---

### ПРОМПТ 3: Full-Stack декомпозиция модуля в Roadmap (Шаг 3)

```markdown
РОЛЬ: Ведущий технический менеджер и архитектор (Lead Full-Stack Engineer & Tech Lead).
ПРОЕКТ: Goliath.

ЗАДАЧА:
Изучить актуальную структуру кодовой базы на GitHub, декомпозировать спецификацию модуля на 3–6 последовательных сквозных задач (Issues) и сформировать файл 03_ROADMAP/[module_slug].md.
НА ЭТОМ ШАГЕ ТЗ ДЛЯ АГЕНТА НЕ ПИШЕТСЯ.

ВХОДНЫЕ ДАННЫЕ:
- Спек-файл модуля: `docs/02_SYSTEM_SPECS/[module_slug].md`
- Системный документ: `technical_blueprint.md`
- Текущая структура каталогов в репозитории на GitHub.

СТРОГИЕ ПРАВИЛА ДЕКОМПОЗИЦИИ (3–6 Full-Stack Issues):
1. Issue 1 (Data Layer & Config-Safe): Модели SQLAlchemy, Alembic-миграция, Pydantic-схема `config_schema.py` и тест валидности конфигурации.
2. Issue 2 (Domain Simulation & Tick DAG): Доменный сервис, бизнес-правила, интеграция шага расчета в глобальный `TickPhase` в модуле ядра.
3. Issue 3 (API & DTO): FastAPI роутер, DTO схемы, авторизация через сессионный Bearer JWT.
4. Issue 4 (Client UI / VKUI): Компоненты панели/модалки VKUI, хуки вызова API, обработка ошибок, вызовы `@vkontakte/vk-bridge`.
5. Issue 5 (Integration / E2E): Сквозной тест сценария без моков (Anti-Mock Guard): действие игрока в UI -> API -> мутация БД -> прогон фазы тика -> верификация финального состояния.
*(Примечание: при компактной логике допускается объединение Issue 2 и 3, но UI и интеграционный тест не могут быть проигнорированы).*

ВЫХОДНЫЕ ДАННЫЕ:
Текст файла `03_ROADMAP/[module_slug].md`:
- Архитектурная цель модуля и границы затрагиваемых директорий.
- Чек-лист всех Issues со статусами:
  - [ ] Issue 1: [Название] — [Scope и архитектурный результат]
  - [ ] Issue 2: [Название] — [Scope и архитектурный результат]
  ...
```

---

### ПРОМПТ 4: Генерация ТЗ для конкретного Issue

```markdown
РОЛЬ: Ведущий full-stack архитектор (Principal Software Architect).
ПРОЕКТ: Goliath.

ЗАДАЧА:
Изучить актуальное состояние в подключенном GitHub-репозитории и сгенерировать токеноэффективное, исчерпывающее техническое задание на английском языке для IDE Agent под указанный Issue.

ВХОДНЫЕ ДАННЫЕ:
- Модуль: `[module_slug]`
- Целевой Issue: `[Номер и точное название задачи из 03_ROADMAP/[module_slug].md]`

ПРАВИЛА ПРОЕКТИРОВАНИЯ ТЗ:
1. Анализ репозитория: Укажите точные пути к существующим файлам, базовым классам и фабрикам тестовых фикстур.
2. Границы изменений:
   - ALLOWLIST: строгий список файлов, разрешенных к созданию и изменению.
   - DENYLIST: чужие модули и таблицы, прямая правка которых категорически запрещена.
3. Межмодульные контракты: Напомните о запрете прямых SQL-мутаций чужих таблиц (только через публичный сервис) и внешних ключей к модулям-сателлитам.
4. Config-Safe: Динамическая загрузка конфига строго через `config_schema.py`. Никакого хардкода баланса.
5. Anti-Mock Guard: Тестирование логики и тика строго на реальной тестовой БД (SQLite in-memory / asyncpg test container) с использованием фабрик фикстур из `backend/tests/fixtures/`.
6. Выдайте строго готовое ТЗ в формате Markdown на английском языке.

ВЫХОДНЫЕ ДАННЫЕ (Англоязычное ТЗ для IDE Agent):
```markdown
# TASK: [module_slug] — Issue [X]: [Issue Description]

## 0. Process
All git operations are Devin's responsibility (commits, branches, merge prep) — Project
Owner only clicks "Merge" after PR is created by Devin on GitHub, after Lead AI review of the diff.

## 1. Scope & Blast Radius
- ALLOWLIST: [Strict list of files permitted to create/edit]
- DENYLIST: [Strictly untouched modules, configs, and foreign migrations]
- Reference Spec: `docs/02_SYSTEM_SPECS/[module_slug].md`
- Runtime Config & Schema: `configs/[module_slug].yaml` & `backend/src/modules/[module_slug]/config_schema.py`

## 2. Architecture & Domain Contracts
- Foreign Key Policy: FKs permitted ONLY to `00_core` tables. Cross-satellite direct FKs are PROHIBITED.
- Inter-Module Mutation: Zero direct SQL mutations on foreign tables. Call public service methods if interacting with dependencies.
- Tick DAG Registration: Handler must be attached strictly to `TickPhase.[PHASE_NAME]` (if applicable).
- Dynamic Balance: All numerical values must be injected via `config_schema.py`. No domain logic hardcoding.
- Authentication: Secure endpoints using Bearer JWT session auth from `00_core`.

## 3. Technical Implementation Details
- Backend (SQLAlchemy / Pydantic / FastAPI / Tick Engine) requirements.
- Frontend (VKUI / React / Vite / VK Bridge) requirements (if within scope of this Issue).
- Error Handling: Specific domain exceptions mapped to clear HTTP status codes.

## 4. Verification & Test Plan (Anti-Mock Guard)
- Test Suite Path: [Exact target path, e.g., `backend/tests/modules/[module_slug]/test_...py`]
- Mandatory Test Scenarios: Happy path, domain invariant violations, edge cases (zero/max values).
- Anti-Mock Guard: State transitions, DB queries, and tick execution must run against a real in-memory test database using factories from `backend/tests/fixtures/`. Shallow mocking of repositories or DB sessions is strictly prohibited.
- Coverage Target: 0 failures, line coverage >= 85%.

## 5. Definition of Done (DoD)
- [ ] Code strictly adheres to ALLOWLIST and Spec contracts.
- [ ] Configuration parsed and validated via Pydantic model.
- [ ] All automated tests pass against a real test database (0 mocks on core state).
- [ ] VKUI components compile without TypeScript errors and conform to responsive design.
- [ ] Commit: `feat([module_slug]): [issue description]`.
```

### ПРОМПТ 5: Стратегический аудит и обзор проекта (Для Мастер-чата)

```markdown
РОЛЬ: Главный системный архитектор и технический директор (Chief Systems Architect / CTO).
ПРОЕКТ: Goliath.

КОНТЕКСТ:
Это постоянный мастер-чат стратегического надзора («Обсерватория проекта»).
Подключенный GitHub-репозиторий — единственный источник истины о текущем прогрессе.

ЗАДАЧА:
Просканировать актуальное состояние репозитория на GitHub и подготовить стратегический отчет о состоянии проекта с высоты птичьего полета:

1. СТАТУС ВЕРТИКАЛЬНЫХ СРЕЗОВ (Full-Stack Realization):
   - Какие модули полностью готовы на всех слоях (БД + Tick DAG + API + VKUI-интерфейс + тесты)?
   - Какие модули существуют только на уровне спецификаций или зависли на этапе бэкенда без UI?

2. ЗДОРОВЬЕ СИМУЛЯЦИИ И TICK DAG:
   - Проверьте оркестратор тика в `00_core`: нет ли конфликтов очередности между зарегистрированными модулями?
   - Все ли формулы и конфиги валидируются соответствующими Pydantic-схемами (`config_schema.py`)?

3. АНАЛИЗ ТЕХНИЧЕСКОГО ДОЛГА И РАДИУСА ВЗРЫВА:
   - Не появились ли запрещенные прямые связи между модулями-сателлитами в обход ядра?
   - Соблюдается ли Anti-Mock Guard в тестовом покрытии?

4. СТРАТЕГИЧЕСКИЙ ВЕКТОР:
   - На каком Issue какого модуля находится команда прямо сейчас?
   - Какой модуль с точки зрения дерева зависимостей и архитектурного графа необходимо взять в разработку следующим?
```