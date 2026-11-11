# syntax=docker/dockerfile:1
# Build from the repository root: docker build -f apps/api/Dockerfile .

FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

FROM base AS deps
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group api

FROM base AS runtime
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data \
    && chown app:app /data
COPY --from=deps /opt/venv /opt/venv
COPY alembic.ini alembic.ini
COPY apps/__init__.py apps/__init__.py
COPY apps/api apps/api
COPY packages packages
USER app
EXPOSE 8000
# 0.0.0.0 is inside the container only. The host side binds 127.0.0.1 in docker-compose.yml.
# Migrations run first. The worker waits for this container to be healthy, so the schema
# is always in place before any job is claimed.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]
