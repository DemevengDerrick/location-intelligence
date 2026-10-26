#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${CREATE_BUCKET:-0}" = "1" ]; then
  python manage.py ensure_bucket
fi

if [ "${COMPILE_MESSAGES:-0}" = "1" ]; then
  python manage.py compilemessages --ignore=.venv >/dev/null
fi

exec "$@"
