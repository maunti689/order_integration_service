#!/bin/sh
set -eu

case "${1:-api}" in
  api)
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    exec celery -A app.workers.celery_app.celery_app worker --loglevel=INFO
    ;;
  beat)
    exec celery -A app.workers.celery_app.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
    ;;
  provider-mock)
    exec uvicorn provider_mock.main:app --host 0.0.0.0 --port 8081
    ;;
  *)
    exec "$@"
    ;;
esac
