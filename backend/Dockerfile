# syntax=docker/dockerfile:1

# Project Goliath — backend image.
# The in-image layout mirrors the repo (/app is the repo root), because
# the code resolves configs/, data/map/ and .env relative to its own
# file location — see docs/02_SYSTEM_SPECS/deploy.md §3.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Non-root runtime user (uid 10001).
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app/backend

# Runtime dependencies only, taken from [project].dependencies of
# backend/pyproject.toml (kept in sync by deriving requirements from the
# file itself). The project and the `dev` extra are NOT installed — the
# app imports via `uvicorn --app-dir src`. This layer is built before
# the source copy so it stays cached across code changes.
COPY backend/pyproject.toml ./pyproject.toml
RUN python -c "import tomllib; open('/tmp/requirements.txt', 'w').write('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
 && pip install --no-cache-dir -r /tmp/requirements.txt

# Source and the repo-root files the app resolves relative to itself:
#   configs/*.yaml   — balance configs, validated at startup
#   data/map/        — whole directory; the map loader requires all six
#                      input files and verifies their hashes
#   backend/alembic* — `migrate` service runs `alembic upgrade head`
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY configs /app/configs
COPY data/map /app/data/map

USER app

EXPOSE 8000

# --workers MUST stay 1: the daily tick scheduler lives in-process
# (backend/src/core/tick/scheduler.py); a second worker would fire the
# same tick twice. Never add --reload here.
CMD ["uvicorn", "main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
