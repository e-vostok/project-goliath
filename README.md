# PAX ATOMICA

Codename: Project Goliath

Пошаговая асинхронная военно-политическая стратегия (ВПИ) для десктопной
экосистемы ВКонтакте: VK Mini App с интерактивной картой мира и «кабинетом
правителя», VK-бот для уведомлений и приказов, а суточный ход рассчитывает
детерминированный серверный движок (Tick DAG) — без ручного вмешательства
и человеческого фактора.

## Статус

- Версия: **v0.12.0** (последний тег `v*`)
- Стек: FastAPI + SQLAlchemy + PostgreSQL · React 18 + TypeScript + Vite + VKUI

## Структура репозитория

- `backend/` — сервер API (FastAPI, SQLAlchemy, Alembic, тесты Anti-Mock Guard)
- `configs/` — боевые конфигурации баланса `*.yaml` (Config-Safe Pattern)
- `data/` — данные карты мира (манифест, геометрия, исходники)
- `deploy/` — скрипты и документация выкладки на сервер
- `docs/` — игровая библия, системные спецификации, дорожные карты модулей
- `frontend/` — клиент VK Mini App (React + VKUI, Desktop-First)
- `tools/` — конвейер подготовки карты и служебные утилиты

## Локальный запуск

Полная инструкция по поднятию dev-окружения (backend, frontend, миграции,
тесты на PostgreSQL) — в файле [RUNNING.md](RUNNING.md).

## Документация

- [PROJECT_STATE.md](docs/PROJECT_STATE.md) — текущее состояние проекта
- [development_workflow.md](docs/development_workflow.md) — регламент разработки
- [01_GAME_BIBLE/](docs/01_GAME_BIBLE/) — правила механик языком геймдизайна
- [02_SYSTEM_SPECS/](docs/02_SYSTEM_SPECS/) — архитектурные спеки и модели данных
- [03_ROADMAP/](docs/03_ROADMAP/) — атомарные задачи (Issues) по модулям
- [changelog.md](changelog.md) — история релизов

## Лицензия

Проект распространяется под лицензией MIT — см. [LICENSE](LICENSE).
