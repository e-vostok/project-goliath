# 🏛️ Project Goliath — Asynchronous Grand Strategy Engine 

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![VKUI](https://img.shields.io/badge/VKUI-6.0+-0077FF?style=flat-square&logo=vk&logoColor=white)](https://vkcom.github.io/VKUI/)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)

> **Project Goliath** — это пошаговая асинхронная военно-политическая стратегия (ВПИ) нового поколения, создаваемая для десктопной экосистемы ВКонтакте на стыке глубокого ролевого отыгрыша и современных веб-технологий. Проект объединяет литературный простор соцсети с мощным веб-приложением: интерактивной картой мира, «кабинетом правителя» и тактическим 2D-варгеймом на гексагональной сетке.

---

## ⚡ Ключевые архитектурные особенности

* **Детерминированный Tick Engine (DAG):** Суточный ход рассчитывается автономным серверным движком по строгому графу зависимостей (Tick DAG). Никакого человеческого фактора, предвзятости администраторов и ручного сведения Google Таблиц.
* **Desktop-First UX:** Проектирование под мониторы высокой четкости (1920×1080) с высокой плотностью информации (High Information Density), управлением мышью и клавиатурой и интерактивной SVG-картой.
* **Тактический 2D-варгейм:** Разрешение военных конфликтов в формате пошаговой тактики на гексах с топографической штабной картой в эстетике классических варгеймов John Tiller.
* **Config-Safe Pattern:** Полная изоляция игрового баланса в `configs/*.yaml`. Все конфигурации строго валидируются типобезопасными Pydantic-схемами при старте приложения и в CI.
* **Anti-Mock Guard:** Принцип жесткого тестирования бизнес-логики и смены ходов исключительно на реальной базе данных (SQLite/PostgreSQL in-memory) с использованием изолированных фабрик фикстур. Поверхностные моки состояния запрещены.
* **Session Auth безопасности VK:** Валидация подписи HMAC-SHA256 и временной метки запуска (`vk_ts`) с мгновенной выдачей сессионного JWT-токена для защиты от Replay-атак.

---

## 🧩 Структура репозитория (Full-Stack Vertical Slices)

Каждая геймплейная подсистема представляет собой сквозной вертикальный срез:

project-goliath/
├── docs/
│   ├── 01_GAME_BIBLE/              # Правила механик на языке геймдизайна
│   ├── 02_SYSTEM_SPECS/            # Архитектурные спеки, FSM, LaTeX-формулы
│   ├── 03_ROADMAP/                 # Атомарные списки задач (Issues) по модулям
│   ├── development_workflow.md     # Производственный стандарт и регламент разработки
│   └── technical_blueprint.md      # Системный технологический чертеж
│
├── configs/                        # Боевые конфигурации баланса движка (*.yaml)
│
├── backend/                        # Серверная часть (FastAPI, SQLAlchemy, Alembic)
│   ├── src/
│   │   ├── core/                   # Ядро: Auth, Session JWT, Tick DAG Orchestrator
│   │   ├── modules/                # Модульные вертикальные срезы логики
│   │   └── main.py                 # Точка входа API
│   └── tests/                      # Интеграционные тесты (Anti-Mock Guard)
│
└── frontend/                       # Клиентское приложение VK Mini App (Desktop)
    ├── src/
    │   ├── app/                    # AppShell, Лейаут, навигация, HUD ресурсов
    │   ├── shared/                 # Базовый API-клиент, утилиты, общие компоненты
    │   └── modules/                # Модульные панели, модалки и хуки интерфейса
    └── vite.config.ts

---

## 🛠️ Технологический стек

| **Backend** | Python 3.13+, FastAPI, SQLAlchemy 2.0 (AsyncIO), Pydantic v2, Alembic |
| **Database** | PostgreSQL, asyncpg, SQLite (тестовый in-memory контур) |
| **Frontend** | React 18, TypeScript, Vite, `@vkontakte/vkui`, `@vkontakte/vk-bridge` |
| **Simulation** | Двумерный холст (Canvas/SVG), собственный Tick DAG Orchestrator |
| **Security** | VK Launch Params HMAC-SHA256, PyJWT (Bearer Token Auth) |
| **CI / Quality** | pytest, pytest-asyncio, flake8/ruff, GitHub Actions |

---

## 📌 Версионирование (Semantic Versioning)

Проект использует строгое семантическое версионирование (**SemVer**): `MAJOR.MINOR.PATCH`:
* **PATCH** (`+0.0.1`): Хотфиксы, корректировка баланса в `configs/*.yaml`.
* **MINOR** (`+0.1.0`): Полный релиз сквозного геймплейного модуля из `docs/03_ROADMAP/`.
* **MAJOR** (`+1.0.0`): Релиз ключевого этапа (Playable Alpha, запуск первого соревновательного сезона).

История всех релизов и изменений документируется в CHANGELOG.md.

---

## 📄 Лицензия

Проект распространяется под лицензией CC0 1.0 Universal. Подробности в файле [LICENSE].
