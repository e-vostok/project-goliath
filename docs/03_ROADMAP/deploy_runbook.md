# 03_ROADMAP / deploy_runbook

Служебная страница бэклога по развёртыванию и боевой инфраструктуре.
Руководство по боевому серверу — `docs/deploy_runbook.md`; роадмап трека deploy — `docs/03_ROADMAP/deploy.md`. Пункты, относящиеся к модулю `02_bot`, хранятся в `docs/03_ROADMAP/02_bot.md` и сюда не дублируются.

## Backlog & Tech Debt

- Ограничение частоты запросов к `/api/v1/bot/callback` и `/api/v1/auth/vk` на уровне Caddy (правки `deploy/Caddyfile`; `/api/v1/auth/vk` — также пункт бэклога `docs/03_ROADMAP/deploy.md`).
