#!/bin/sh
set -eu

# Хранилище Amvera монтируется в /data и может принадлежать root.
# Выдаём права непривилегированному пользователю и сбрасываем root-привилегии.
mkdir -p "${DATA_DIR:-/data}"
if [ "$(id -u)" = "0" ]; then
  chown -R app:app "${DATA_DIR:-/data}" 2>/dev/null || true
  chmod 0700 "${DATA_DIR:-/data}" 2>/dev/null || true
  exec setpriv --reuid=app --regid=app --clear-groups --no-new-privs \
    "$0" "$@"
fi

umask 077
if [ "$#" -gt 0 ]; then exec "$@"; fi

# Один воркер: Telegram-сессия и in-memory лимиты живут в одном процессе
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-3000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips "*" \
  --no-access-log \
  --no-server-header \
  --timeout-graceful-shutdown 10
