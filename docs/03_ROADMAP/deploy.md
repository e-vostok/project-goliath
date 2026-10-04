# 03_ROADMAP / deploy

## Статус

Служебный инфраструктурный трек (не игровой модуль: нет Game Bible, таблиц БД и фазы тика). Контракт — `docs/02_SYSTEM_SPECS/deploy.md` (версия 1.0).

## Архитектурная цель

Боевой сервер (пока он же staging) на одном VPS в РФ: Docker Compose (`db`, `migrate`, `backend` с одним воркером, `caddy`), один домен, автоматический HTTPS. Обновления накатываются из GitHub одной командой с бэкапом, миграциями и проверкой здоровья; суточный ход работает автономно и защищён от двойного запуска; есть бэкапы с проверенным восстановлением.

## Границы затрагиваемых директорий

- `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.prod.yml`, `deploy/` (Caddyfile, скрипты), `.dockerignore`, `.env.prod.example` — новое
- `.github/workflows/` — новое (CI, позже деплой)
- `backend/src/core/tick/`, `backend/src/core/admin/`, `backend/src/main.py`, `backend/src/core/security/` — точечные правки (Issues DEP-3, DEP-4)
- `docs/deploy_runbook.md` — новое; `RUNNING.md`, `changelog.md` — дополнения
- Не затрагиваются: игровая логика модулей, миграции, `configs/*.yaml`, `data/`, `tools/`

## Предусловия (вне трека, трек Б)

До первого боевого деплоя закрыты два уже выданных багфикса: синхронный драйвер PostgreSQL для alembic и удаление государства с `scheduled_actions`.

## Порядок

DEP-1 → DEP-2 → DEP-3 → DEP-4 → DEP-5 → **веха M1: первый ручной деплой владельцем** → DEP-6.
Относительно черновика владельца изменено: CI (DEP-2) идёт раньше защиты тика, чтобы тесты на реальном PostgreSQL запускались на каждом PR, начиная с самой рискованной задачи (DEP-3); предохранители боевого режима выделены в отдельный Issue DEP-4.

## Issues

- [x] **DEP-1: Контейнеризация** — `backend/Dockerfile` (tzdata, не root, раскладка как в репозитории, данные карты), `frontend/Dockerfile` (сборка → Caddy), `deploy/Caddyfile`, `docker-compose.prod.yml` (db, migrate, backend, caddy, healthchecks, ротация логов), `.dockerignore`, `.env.prod.example`. Приёмка: на пустой базе стек поднимается целиком, `migrate` отрабатывает, `game_clock` существует, планировщик стартует, `/` и `/api/*` отвечают через Caddy. Runtime acceptance (`deploy/smoke_local.sh`) was not run — Docker unavailable on the dev machine; it is executed in DEP-2 CI on a Linux runner. Runtime acceptance closed by DEP-2 CI.
- [x] **DEP-2: CI на GitHub Actions** — PostgreSQL-сервис, полный `pytest` включая маркер `postgres` (`REQUIRE_POSTGRES_TESTS=1`), тест валидности конфигов, защитный тест дрейфа миграций, фронтенд (типы, тесты, сборка), проверка сборки обоих образов и `docker compose config`. Без секретов, права `contents: read`, запуск на PR и push в `main`.
- [x] **DEP-3: Защита хода и живучесть планировщика** — advisory lock + перепроверка `next_tick_at` под `FOR UPDATE` (только автоматический путь), блокировка до записи `RUNNING`, цикл планировщика переживает ошибки БД, «метка жизни»; тесты на реальном PostgreSQL (двойной запуск → один ход).
- [x] **DEP-4: Предохранители боевого режима** — `GET /api/v1/health` (БД + метка планировщика, 200/503), флаг `ADMIN_ALLOW_RESET` (403 `RESET_DISABLED`), отказ запуска при слабом `JWT_SECRET_KEY`/dev-значениях при `APP_ENV=production`; тесты.
- [x] **DEP-5: Операционные скрипты и runbook** — `deploy.sh`, `backup.sh`, `restore_check.sh`, `docs/deploy_runbook.md` (настройка сервера, деплой, откат, восстановление, ротация логов, окно 23:55–00:10; первый запуск: на свежей базе миграция 0001 ставит первый ход через 24 часа от момента миграции, а не на 00:00 по Москве — после первого деплоя один раз выровнять расписание кнопкой «Запустить ход» в админ-панели — без сброса мира, поправлено в DEP-6a), проверка скриптов (shellcheck) в CI.
- [x] **DEP-6a: Фиксация зависимостей бэкенда** — `backend/requirements.lock` + `requirements-dev.lock` (`uv pip compile`, цель Python 3.12 / manylinux_2_28), установка в образе и CI через `-c`, freshness-guard в job `backend`, parity-guard (`pip freeze` ⊇ lock) в job `docker`, снят psycopg2-override `DATABASE_URL` у `migrate` (env.py сам конвертирует asyncpg-URL). Хэши в lock'ах — в бэклоге.
- [ ] **DEP-6: Автодеплой по тегу или кнопке** — `.github/workflows/deploy.yml` (`push` тега `v*` и `workflow_dispatch`, Environment `production` с подтверждением владельцем, SSH-ключ в GitHub Secrets, ограниченная команда), закрытие трека: MINOR-версия v0.5.0, `changelog.md`, релизный тег.

## Версия релиза

Трек закрывается MINOR-версией (по правилам `development_workflow.md`: релиз завершённого набора Issues). Модуль `01_map` уже выпущен как v0.4.0 (03.10.2026), поэтому трек deploy выходит как **v0.5.0**. Если до закрытия трека выйдет другой MINOR-релиз, берём следующий свободный номер.

## Ручные шаги владельца (детализируются чеклистами по ходу)

Выбор провайдера и заказ сервера → домен и DNS-запись A → SSH-ключ и первичная защита сервера → боевой `.env` с новыми секретами → адреса приложения в `dev.vk.com` → первый ручной деплой (веха M1) → позже настройка Callback API (спринт бота).

## Backlog & Tech Debt

- Сборка образов в GitHub Actions и загрузка на сервер из реестра (если на сервере 2 ГБ памяти или Docker Hub недоступен).
- Заголовки `X-Frame-Options`/`frame-ancestors` — после проверки в живом ВК.
- Внешний монитор доступности `/api/v1/health` и оповещения (Telegram/ВК — в спринте бота).
- Скрыть кнопку «Сбросить мир» в интерфейсе, когда `ADMIN_ALLOW_RESET=false` (сейчас сервер отвечает 403, интерфейс показывает ошибку).
- Ограничение частоты запросов к `/api/v1/auth/vk`.
- Отдельный staging рядом с боевым — перед настоящим запуском для игроков.
- Регулярная автоматическая проверка восстановления бэкапа.
