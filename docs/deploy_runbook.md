# Руководство по боевому серверу (runbook)

Этот документ — для владельца проекта, не для программиста. Каждая команда
даётся целиком, чтобы её можно было скопировать и вставить в терминал.
Перед каждым разделом коротко написано, зачем это нужно.

Обозначения:

- `ваш-домен.ru` — замените на настоящий домен.
- `<...>` — то, что нужно подставить своё.
- Команды выполняются на сервере, если не сказано «на вашем компьютере».

---

## 1. Схема и где что лежит

Зачем: чтобы понимать, из чего состоит игра на сервере и где искать файлы.

```
Интернет → https://ваш-домен.ru → caddy (порты 80/443)
                                   ├── /        → статика фронтенда
                                   └── /api/*   → backend:8000 → db (PostgreSQL)
```

Стек поднимается одной командой `docker compose` из файла
`docker-compose.prod.yml`. Четыре сервиса:

- `db` — база данных PostgreSQL, наружу не выставлена;
- `migrate` — одноразовый контейнер, применяет миграции и завершается;
- `backend` — игровой сервер (FastAPI, один воркер);
- `caddy` — принимает HTTPS, отдаёт фронтенд, сам выпускает сертификат.

Где что лежит на сервере (вход по SSH под пользователем `deploy`):

| Что | Где |
|:--|:--|
| Репозиторий игры | `/opt/goliath` |
| Секретные настройки | `/opt/goliath/.env` (права 600) |
| Скрипты | `/opt/goliath/deploy/` |
| Бэкапы на сервере | `/home/deploy/backups/` (`daily/`, `predeploy/`, `backup.log`, `LAST_OK`) |
| Настройки внешней копии | `/home/deploy/.config/goliath/backup.env` |
| Расписание бэкапов | `crontab -e` (шаблон: `deploy/cron.example`) |
| Данные PostgreSQL | Docker-том `goliath_pgdata` (меняется только через дампы!) |
| Сертификаты | Docker-тома `goliath_caddy_data`, `goliath_caddy_config` |

---

## 2. Настройка нового сервера (Ubuntu 24.04)

Зачем: один раз подготовить чистый сервер — отдельный пользователь,
вход только по ключу, файрвол, подкачка, автообновления, Docker.

Всё делается один раз. Заходите на сервер под тем пользователем, которого
дал хостер (обычно `root` или `ubuntu`), по SSH-ключу.

### 2.1. Пользователь deploy и вход по ключу

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo mkdir -p /home/deploy/.ssh
sudo cp ~/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

Откройте **второе** окно терминала и проверьте, что вход работает:
`ssh deploy@<IP-сервера>`. Только после успешного входа продолжайте.

### 2.2. Отключить вход по паролю и root

```bash
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/60-goliath.conf
sudo systemctl reload ssh
```

### 2.3. Файрвол (открыть только 22, 80, 443)

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

На вопрос отвечайте `y`. Проверка: `sudo ufw status`.

### 2.4. Файл подкачки 2 ГБ и умеренный swappiness

Зачем: на дешёвом VPS памяти мало; подкачка спасает от падения при сборке
образов. `swappiness=10` — использовать её только когда совсем тесно.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
printf 'vm.swappiness=10\n' | sudo tee /etc/sysctl.d/90-goliath.conf
sudo sysctl --system
```

Проверка: `free -h` — в строке Swap должно быть около 2Gi.

### 2.5. Автоматические обновления безопасности

```bash
sudo apt-get update
sudo apt-get install -y unattended-upgrades
printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades
```

### 2.6. Docker

```bash
sudo apt-get install -y docker.io docker-compose-v2 docker-buildx
sudo usermod -aG docker deploy
```

Перелогиньтесь под `deploy` (выйдите и зайдите снова), затем проверьте:

```bash
docker version
docker compose version
```

Обе команды должны отвечать версиями без `sudo` и без ошибок.

### 2.7. Папка проекта и клон репозитория

```bash
sudo mkdir -p /opt/goliath
sudo chown deploy:deploy /opt/goliath
exit   # выйти из-под root/ubuntu, если ещё там
```

Дальше — только под `deploy`:

```bash
git clone https://github.com/e-vostok/project-goliath /opt/goliath
cd /opt/goliath
```

---

## 3. Боевой `.env`

Зачем: один файл со всеми секретами и настройками. Без него стек не
поднимется; с чужими секретами в него никого не пускайте.

```bash
cd /opt/goliath
cp .env.prod.example .env
chmod 600 .env
nano .env
```

Что вписать (в `nano`: редактируете, затем `Ctrl+O`, Enter, `Ctrl+X`):

| Ключ | Откуда взять |
|:--|:--|
| `DOMAIN` | ваш домен, без `https://`, например `goliath.example.ru`. DNS A-запись уже должна смотреть на сервер! |
| `ACME_EMAIL` | ваша почта (для Let's Encrypt) |
| `POSTGRES_USER` | оставьте `goliath` |
| `POSTGRES_DB` | оставьте `goliath` |
| `POSTGRES_PASSWORD` | сгенерируйте: `openssl rand -hex 24` |
| `DATABASE_URL` | `postgresql+asyncpg://goliath:<ТОТ ЖЕ ПАРОЛЬ>@db:5432/goliath` — пароль внутри должен совпадать с `POSTGRES_PASSWORD` символ в символ |
| `JWT_SECRET_KEY` | сгенерируйте: `openssl rand -hex 32` |
| `VK_APP_SECRET` | секрет мини-приложения из кабинета dev.vk.com |
| `ADMIN_VK_USER_IDS` | ваш числовой id ВКонтакте, например `123456789` |
| `APP_ENV` | `production` (уже прописано) |
| `ADMIN_ALLOW_RESET` | `false` (уже прописано; о `true` — раздел 5) |

Правила безопасности:

- Никогда не отправляйте значения из `.env` в чаты и мессенджеры —
  ни целиком, ни «проверьте, правильно ли».
- Файл должен остаться с правами 600: проверьте `ls -l .env` —
  должно быть `-rw-------`.
- Пароль БД — только буквы и цифры (`openssl rand -hex` так и делает):
  он подставляется внутрь адреса подключения.

Проверка перед деплоем: `./deploy/deploy.sh --check` — скрипт сам
перечислит, что забыли.

---

## 4. Первый деплой

Зачем: впервые поднять игру на сервере. Отличается от обычного
обновления тем, что базы ещё нет (бэкап пропускается — так и задумано)
и выпускается сертификат.

```bash
cd /opt/goliath
./deploy/deploy.sh --check     # только проверки; исправьте, если ругается
./deploy/deploy.sh             # сам деплой
```

Первый запуск долгий: скачиваются и собираются образы (ориентир —
5–15 минут). Ничего не прерывайте.

Как выглядит успех:

- последние строки: `Deploy OK`, таблица `docker compose ps` —
  `db`, `backend`, `caddy` в статусе `running`/`healthy`;
- откройте в браузере `https://ваш-домен.ru/api/v1/health` —
  должно быть `{"status":"ok",...}`;
- `https://ваш-домен.ru` — загружается игра.

Если что-то пошло не так — скрипт печатает большой блок «ЧТО ДЕЛАТЬ:
ОТКАТ». Читайте его, не паникуйте: до первого успешного деплоя терять
нечего, достаточно исправить причину и запустить `./deploy/deploy.sh`
ещё раз.

---

## 5. Выравнивание первого хода на 00:00 МСК

Зачем: первая миграция ставит первый ход «через 24 часа от момента
установки», а игра должна ходить ровно в полночь по Москве. Делается
один раз, сразу после первого деплоя.

1. Откройте `https://ваш-домен.ru` под своим ВК-аккаунтом
   администратора и зайдите в админ-панель.
2. Нажмите **«Запустить ход»** один раз. Сервер немедленно проведёт
   ход, и `finalize_tick` сам поставит следующий ход на ближайшие
   00:00 по Москве. Мир при этом **не стирается** — нации и провинции
   остаются на месте, `ADMIN_ALLOW_RESET` включать не нужно.
3. Проверьте время следующего хода в админ-панели — должно стоять
   ближайшее 00:00 по Москве.

Счётчик ходов при этом станет 1 — до запуска это нормально. Полный
сброс мира «с чистого листа» делается один раз, непосредственно перед
настоящим запуском для игроков.

---

## 6. Обычное обновление

Зачем: накатить новую версию игры. Одна команда делает всё: проверки,
бэкап, переход на нужный тег, сборку, миграции, запуск и проверку
здоровья.

```bash
cd /opt/goliath
./deploy/deploy.sh --ref v0.5.0
```

- Без `--ref` ставится последний `main`: `./deploy/deploy.sh`.
- **Запретное окно:** с 23:55 до 00:10 по Москве скрипт откажется
  работать — в это время идёт суточный ход, и деплой мог бы его
  сломать. Если ход важно не пропустить — подождите. Если точно
  знаете, что делаете (например, ход сейчас не критичен):
  `./deploy/deploy.sh --ref v0.5.0 --force`.
- При сбое читайте блок «ЧТО ДЕЛАТЬ: ОТКАТ» в конце вывода —
  скрипт сам ничего не откатывает.

### 6.1. Если релиз выводит узлы карты (retired): проверка до выкладки

Зачем: иногда релиз выводит часть провинций из игры (в примечаниях к
релизу это помечается словом retired). Если выведенная провинция ещё
принадлежит государству или у неё есть история в журнале, новый сервер
откажется запускаться — лучше узнать об этом до деплоя, а не во время
него. Проверка занимает пару минут и ничего не меняет в базе: только
читает.

Выполняйте на сервере под `deploy`, когда релиз выводит узлы карты.
Если релиз карту не трогал — раздел можно пропустить.

```bash
cd /opt/goliath
# → ничего не напечатает — вы в папке проекта

git fetch --tags
# → покажет новые теги или ничего — оба варианта в порядке

git checkout --detach <тег-релиза>
# → ответит «HEAD is now at ...» — вы на коде нового релиза

docker compose -f docker-compose.prod.yml build backend
# → сборка образа, несколько минут; в конце не должно быть слова ERROR

export COMPOSE_FILE=docker-compose.prod.yml
# → ничего не напечатает — так и надо: запоминает имя compose-файла

docker compose run --rm --no-deps backend python -m src.modules._01_map.retired_report
# → печатает отчёт по базе, последняя строка — вердикт (читаем ниже)
```

Как читать вердикт:

- `ГОТОВО: запуск пройдёт, будет удалено N строк` — база готова к
  релизу, выкладывайте штатно: `./deploy/deploy.sh --ref <тег-релиза>`.
- `СТОП: запуск остановится` — **не выкладывайте**: выведенные
  провинции заняты государствами или хранят историю. Скопируйте весь
  вывод целиком и пришлите Lead-разработчику — он решит, что делать.
- Вместо отчёта одна строка вида `INV_M*: ...` (программа завершилась
  кодом 2) — испорчены сами файлы карты в релизе. Тоже не выкладывайте
  и пришлите вывод Lead-разработчику.

После удачной выкладки запустите последнюю команду ещё раз: в строке
«Выведенные узлы со строками в provinces» должно стоять `0` — новый
сервер при первом запуске уже удалил эти строки сам.

---

## 7. Откат

Зачем: вернуть прошлую версию, если после обновления что-то сломалось.
Две независимые части: код и база. Базу откатывайте только если она
действительно пострадала (обычно достаточно отката кода).

### 7.1. Откат кода

```bash
cd /opt/goliath
git checkout --detach <предыдущий-коммит>   # скрипт печатал его как PREV_SHA
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Проверка: `https://ваш-домен.ru/api/v1/health` → `{"status":"ok"}`.

### 7.2. Откат базы из преддеплойного бэкапа

Миграции идут только вперёд, поэтому базу возвращаем восстановлением
из дампа, который `deploy.sh` сделал перед деплоем
(`~/backups/predeploy/`). Имена файлов — в блоке отката или
`ls -lt ~/backups/predeploy/`.

```bash
cd /opt/goliath
DUMP=~/backups/predeploy/goliath-predeploy-XXXXXXXX-XXXXXX.dump   # подставьте имя файла
PGU=$(grep '^POSTGRES_USER=' .env | cut -d= -f2-)
PGD=$(grep '^POSTGRES_DB=' .env | cut -d= -f2-)

docker compose -f docker-compose.prod.yml --env-file .env stop backend
docker compose -f docker-compose.prod.yml --env-file .env exec -T db \
  psql -U "$PGU" -d postgres -c "DROP DATABASE \"$PGD\" WITH (FORCE)"
docker compose -f docker-compose.prod.yml --env-file .env exec -T db \
  psql -U "$PGU" -d postgres -c "CREATE DATABASE \"$PGD\""
cat "$DUMP" | docker compose -f docker-compose.prod.yml --env-file .env \
  exec -T db pg_restore -U "$PGU" -d "$PGD" --no-owner --exit-on-error
docker compose -f docker-compose.prod.yml --env-file .env up -d backend
```

Проверка: health → ok, затем зайдите в игру и убедитесь, что мир
выглядит как до обновления.

---

## 8. Бэкапы

Зачем: два слоя защиты — свежие дампы на самом сервере (быстрый откат)
и шифрованные копии вне сервера (на случай гибели самого сервера).
Дампы содержат id игроков ВКонтакте — внешняя копия поэтому шифруется.

### 8.1. Расписание (cron)

```bash
timedatectl      # посмотрите строку "Time zone"
crontab -e
```

Вставьте в конец две строки из `deploy/cron.example`. Если сервер в
UTC — как есть (21:30 UTC = 00:30 МСК). Если в другом поясе —
пересчитайте час, чтобы бэкап шёл около 00:30 по Москве.

Проверка через сутки: `cat ~/backups/LAST_OK` и `tail ~/backups/backup.log`.

### 8.2. Внешняя копия: шифрование age

Логика такая: на сервере лежит только **публичный** ключ (им шифруют),
а **приватный** ключ, которым можно расшифровать бэкапы, хранится у вас
офлайн — даже полный доступ к серверу не даст читать старые копии.

На **вашем компьютере** (Windows):

1. Скачайте `age` для Windows со страницы релизов:
   https://github.com/FiloSottile/age/releases (файл вида
   `age-vX.X.X-windows-amd64.zip`), распакуйте.
2. В папке с распакованным `age-keygen.exe` откройте терминал
   (Shift + правая кнопка → «Открыть окно PowerShell здесь») и выполните:

   ```powershell
   .\age-keygen.exe -o goliath-backup-key.txt
   ```

3. Программа напечатает публичный ключ вида `age1...` — он же будет
   в первой строке файла. Публичный ключ понадобится на сервере.
4. Сам файл `goliath-backup-key.txt` — это приватный ключ. Сохраните
   его надёжно и офлайн (флешка в ящике стола + копия). На сервер
   его не загружайте никогда.

### 8.3. Внешняя копия: хранилище через rclone

Нужно любое S3-совместимое хранилище (например, бакет у вашего
облачного провайдера). На сервере один раз настройте remote:

```bash
sudo apt-get install -y age rclone    # если ещё не установлены
rclone config
```

Дальше по шагам мастера: `n` (new remote) → имя, например
`goliath-backup` → тип `S3` → провайдер вашего хранилища → ключи
доступа и endpoint → остальное можно пропускать Enter'ом → `q`.
Проверка: `rclone lsd goliath-backup:` — покажет ваши бакеты.

### 8.4. Файл настроек бэкапов

```bash
mkdir -p ~/.config/goliath
nano ~/.config/goliath/backup.env
chmod 600 ~/.config/goliath/backup.env
```

Содержимое (подставьте своё):

```dotenv
BACKUP_AGE_RECIPIENT=age1публичный_ключ_из_п_8.2
BACKUP_RCLONE_REMOTE=goliath-backup:имя-бакета
BACKUP_OFFSITE_KEEP_DAYS=30
```

### 8.5. Первый запуск вручную и репетиция

```bash
cd /opt/goliath
./deploy/backup.sh --tag daily
```

Успех: строка «Бэкап завершён: локальная копия + внешняя». Если внешняя
копия не настроена — скрипт громко предупредит и завершится кодом 2.

Репетиция восстановления (не трогает живую базу):

```bash
./deploy/restore_check.sh        # проверит самый свежий дамп -> PASS
```

Раз в месяц она и так запускается по cron (вторая строка), но после
настройки прогоните вручную.

---

## 9. Восстановление на новом сервере из внешней копии

Зачем: сервер сгорел / переезжаем — поднять игру с нуля из шифрованной
копии. Приватный ключ живёт только на вашем компьютере, поэтому
расшифровка делается там.

1. Поднимите чистый сервер по разделу 2 (кроме клона — можно сразу).
2. На **сервере** скачайте последний зашифрованный дамп (rclone
   настраивается как в п. 8.3, нужен тот же remote):

   ```bash
   rclone lsl goliath-backup:имя-бакета        # выберите самый свежий файл
   rclone copy goliath-backup:имя-бакета/goliath-daily-XXXX.dump.age ~/
   ```

3. Перекиньте файл `goliath-daily-XXXX.dump.age` на свой компьютер
   (например, через WinSCP).
4. На **вашем компьютере** расшифруйте (в папке с `age.exe`):

   ```powershell
   .\age.exe -d -i goliath-backup-key.txt -o goliath.dump goliath-daily-XXXX.dump.age
   ```

5. Загрузите `goliath.dump` обратно на сервер (WinSCP, в `/home/deploy/`).
6. Дальше — как в п. 7.2: остановите backend, пересоздайте базу,
   `pg_restore` из файла `~/goliath.dump`, запустите backend.
7. Проверка: health → ok и вход в игру.

---

## 10. Если что-то сломалось

Зачем: короткая шпаргалка по симптомам.

**`https://домен/api/v1/health` отвечает 503.**

Смотрите, какая проверка не в порядке (в ответе JSON, поле `checks`):

- `"database":"fail"` — база недоступна: `docker compose -f
  docker-compose.prod.yml --env-file .env ps db`, логи
  `... logs --tail=100 db`. Часто — кончилось место (`df -h`).
- `"scheduler":"stale"` или `"never"` — планировщик ходов не
  работает: логи `... logs --tail=100 backend`, журнал ходов —
  в админ-панели игры.

**Сайт вообще не открывается, ошибка сертификата.**

- DNS A-запись указывает на сервер? `ping ваш-домен.ru`.
- Порты 80/443 открыты? `sudo ufw status`.
- Логи Caddy: `docker compose -f docker-compose.prod.yml --env-file .env
  logs --tail=100 caddy` — видно, на что ругается выпуск сертификата.

**Кончилось место на диске.**

```bash
df -h /
docker system df
docker system prune            # удалит неиспользуемые образы/сети
ls -lt ~/backups/daily | head  # старые дампы чистятся сами (хранятся 14)
```

**Посмотреть логи любого сервиса:**

```bash
cd /opt/goliath
docker compose -f docker-compose.prod.yml --env-file .env logs --tail=100 backend
docker compose -f docker-compose.prod.yml --env-file .env logs --tail=100 db
docker compose -f docker-compose.prod.yml --env-file .env logs --tail=100 caddy
docker compose -f docker-compose.prod.yml --env-file .env logs migrate
```

**Узнать статус контейнеров:**

```bash
docker compose -f docker-compose.prod.yml --env-file .env ps
```

**Бэкап по cron не отработал:** `tail ~/backups/cron.log` и
`tail ~/backups/backup.log` — там причина на русском.

---

## 11. Чек-лист «готов к тестировщикам»

Зачем: финальный проход перед тем, как позвать людей.

- [ ] `https://ваш-домен.ru/api/v1/health` → `{"status":"ok"}`
- [ ] `https://ваш-домен.ru` открывается по HTTPS без предупреждений
- [ ] Вход через ВКонтакте работает, админ-панель доступна вам
- [ ] Время следующего хода в админ-панели — 00:00 по Москве
- [ ] `ADMIN_ALLOW_RESET=false` в `.env` (`grep ADMIN_ALLOW_RESET .env`)
- [ ] `ls -l .env` → права `-rw-------`
- [ ] `cat ~/backups/LAST_OK` — свежая дата; `crontab -l` — две строки
- [ ] `./deploy/backup.sh --tag daily` → «локальная копия + внешняя»
- [ ] `./deploy/restore_check.sh` → `PASS`
- [ ] Приватный ключ age сохранён офлайн у владельца, на сервере его нет
- [ ] `ssh` входит только по ключу; `sudo ufw status` — только 22/80/443
- [ ] `df -h /` — свободно больше 3 ГБ

---

## 12. Как обновить зависимости

Зачем: версии всех Python-пакетов бэкенда зафиксированы в файлах
`backend/requirements.lock` (боевые) и `backend/requirements-dev.lock`
(боевые + инструменты разработки). Боевой образ и CI ставят ровно эти
версии, поэтому обновление делается только осознанно — этой процедурой.

**Никогда не правьте файлы `requirements*.lock` руками.** Они
генерируются командой и должны оставаться синхронными с
`backend/pyproject.toml` — CI это проверяет и падает, если они
разошлись.

Порядок (на компьютере разработчика; нужен `uv` — ставится командой
`pip install uv`):

```bash
cd backend
uv pip compile pyproject.toml --upgrade --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o requirements.lock
uv pip compile pyproject.toml --extra dev --upgrade --python-version 3.12 --python-platform x86_64-manylinux_2_28 -o requirements-dev.lock
```

Флаг `--upgrade` поднимает все пакеты до самых свежих версий,
разрешённых рамками в `pyproject.toml`. Если нужно обновить только
одну библиотеку — сначала поднимите её нижнюю границу в
`pyproject.toml`, затем выполните те же команды **без** `--upgrade`:
остальные версии останутся как были.

Затем:

1. Прогнать тесты: `pytest` из папки `backend/`.
2. Закоммитить **оба** lock-файла вместе с `pyproject.toml` одним
   коммитом.
