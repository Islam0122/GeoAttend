#!/bin/sh
set -e
case "$1" in
  api)
    # Migrations run once at API start (idempotent); worker and beat never migrate.
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-4}" --proxy-headers --forwarded-allow-ips="*"
    ;;
  worker)
    exec celery -A app.tasks.celery_app worker --loglevel="${CELERY_LOG_LEVEL:-INFO}" --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A app.tasks.celery_app beat --loglevel="${CELERY_LOG_LEVEL:-INFO}" --schedule=/app/run/celerybeat-schedule
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    exec "$@"
    ;;
esac
