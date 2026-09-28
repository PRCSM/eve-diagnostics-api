#!/bin/sh
set -eu

# Convenient for local/demo use. In production, run migrations as a separate release step
# and set RUN_MIGRATIONS=false here.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
