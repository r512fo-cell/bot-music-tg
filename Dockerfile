# syntax=docker/dockerfile:1

# ---------- 1. Сборка фронтенда (Vue + Vite) ----------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Рантайм (Python) ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    PORT=3000 \
    DENO_DIR=/tmp/deno \
    XDG_CACHE_HOME=/tmp/.cache \
    DENO_NO_UPDATE_CHECK=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --system --uid 10001 --user-group --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data

COPY --chown=root:root backend/app ./app
COPY --chown=root:root --from=frontend /build/dist ./static
COPY --chown=root:root docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"3000\")}/health', timeout=4)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
