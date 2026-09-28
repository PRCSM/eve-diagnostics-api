# syntax=docker/dockerfile:1

# ---- base: runtime dependencies ------------------------------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app \
    && chown app:app /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- dev: adds test/lint tooling (used by the "tests" compose service) ---------------------
FROM base AS dev
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY --chown=app:app . .
USER app
CMD ["pytest", "-q"]

# ---- runtime: the default (last) stage ------------------------------------------------------
FROM base AS runtime
COPY --chown=app:app . .

# collectstatic imports settings, which refuse to start without secrets when DEBUG is off.
# These throwaway values exist only for this build step and are not kept in the image env.
RUN DJANGO_SECRET_KEY=build-only JWT_SIGNING_KEY=build-only PAYMENT_WEBHOOK_SECRET=build-only \
    POSTGRES_PASSWORD=build-only python manage.py collectstatic --noinput \
    && chown -R app:app /app/staticfiles

USER app
EXPOSE 8000
ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--timeout", "30", "--graceful-timeout", "30"]
