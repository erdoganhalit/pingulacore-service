#!/usr/bin/env sh
set -eu

if [ "${SKIP_DB_MIGRATIONS:-0}" != "1" ]; then
  echo "[entrypoint] Running Alembic migrations..."
  if command -v alembic >/dev/null 2>&1; then
    alembic upgrade head
  else
    uv run alembic upgrade head
  fi
fi

if [ "$#" -eq 0 ]; then
  set -- uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

exec "$@"
