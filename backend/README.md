# Backend — Project Goliath

## Миграции базы данных

Alembic **всегда** нацелен на ту же базу, что и приложение: `DATABASE_URL`
берётся из окружения процесса, а если переменной нет — из `.env` в корне
репозитория (привязка к корню, поэтому команды работают и из `backend/`,
и из `backend/src/`). Тихого fallback на SQLite нет: если URL не найден,
команда падает с ошибкой, называющей `DATABASE_URL` и проверенный `.env`.
Перед любой миграцией alembic печатает одну строку с целевой базой
(пароль замаскирован), например:

```text
Alembic target: postgresql+asyncpg://goliath_user:***@localhost:5432/goliath_dev
```

Команды (запускать из каталога `backend/`):

```bash
alembic current        # показать текущую ревизию БД
alembic upgrade head   # применить миграции до head
```

Если в выводе `Alembic target:` не та база — остановитесь и проверьте
`DATABASE_URL` в окружении и в корневом `.env`.
