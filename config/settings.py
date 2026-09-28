"""Django settings, driven entirely by environment variables (see .env.example)."""

from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_list, env_str, load_env_file

BASE_DIR = Path(__file__).resolve().parent.parent
load_env_file(BASE_DIR / ".env")

DEBUG = env_bool("DJANGO_DEBUG", default=False)


def _secret(name: str, dev_default: str) -> str:
    """Return a secret from the environment; only fall back to a dev value when DEBUG is on."""
    value = env_str(name)
    if value:
        return value
    if DEBUG:
        return dev_default
    raise ImproperlyConfigured(f"{name} must be set when DJANGO_DEBUG is false.")


SECRET_KEY = _secret("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "apps.common",
    "apps.accounts",
    "apps.catalog",
    "apps.bookings",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.common.middleware.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database -------------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env_str("POSTGRES_DB", "eve"),
        "USER": env_str("POSTGRES_USER", "eve"),
        "PASSWORD": _secret("POSTGRES_PASSWORD", "eve-dev-password"),
        "HOST": env_str("POSTGRES_HOST", "127.0.0.1"),
        "PORT": env_str("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        # Fail fast instead of hanging requests when the database is unreachable.
        "OPTIONS": {"connect_timeout": env_int("POSTGRES_CONNECT_TIMEOUT", 5)},
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -----------------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18N / time ----------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # API renders times in IST; the database stores UTC.
USE_I18N = True
USE_TZ = True

# --- Static files (Django admin, served by WhiteNoise) --------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Request bodies are small JSON documents; cap them to limit abuse.
DATA_UPLOAD_MAX_MEMORY_SIZE = 256 * 1024

# --- Security headers -----------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
# Preload-list submission is hard to undo, so it's a deliberate opt-out rather than a default.
SECURE_HSTS_PRELOAD = False
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", default=not DEBUG)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Cache (throttle counters) --------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "eve-default",
    }
}

# --- Django REST framework ------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # Secure by default: every endpoint requires authentication unless it opts out.
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "120/min",
        "login": "10/min",
        "signup": "10/hour",
        "payments": "20/min",
        "webhook": "600/min",
    },
    "EXCEPTION_HANDLER": "apps.common.exception_handler.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "NUM_PROXIES": env_int("DJANGO_NUM_PROXIES", 0) or None,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_TTL_MINUTES", 15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_TTL_DAYS", 7)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": _secret("JWT_SIGNING_KEY", "dev-only-insecure-jwt-signing-key-change-me"),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

API_DOCS_ENABLED = env_bool("API_DOCS_ENABLED", default=True)

SPECTACULAR_SETTINGS = {
    "TITLE": "EVE Diagnostics API",
    "DESCRIPTION": (
        "Diagnostic test bookings with simulated payments and an idempotent payment webhook."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
}

# --- Domain settings ------------------------------------------------------------------------

PAYMENT_WEBHOOK_SECRET = _secret("PAYMENT_WEBHOOK_SECRET", "dev-only-webhook-secret-change-me")
PAYMENT_WEBHOOK_TOLERANCE_SECONDS = env_int("PAYMENT_WEBHOOK_TOLERANCE_SECONDS", 300)
PAYMENT_SIMULATION_DEFAULT_OUTCOME = env_str("PAYMENT_SIMULATION_DEFAULT_OUTCOME", "SUCCESS")
BOOKING_MAX_ADVANCE_DAYS = env_int("BOOKING_MAX_ADVANCE_DAYS", 90)

# --- Logging --------------------------------------------------------------------------------

LOG_LEVEL = env_str("LOG_LEVEL", "INFO")
LOG_FORMAT = env_str("LOG_FORMAT", "json")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_context": {"()": "apps.common.logging.RequestContextFilter"},
        "redact": {"()": "apps.common.logging.RedactionFilter"},
    },
    "formatters": {
        "json": {"()": "apps.common.logging.JsonFormatter"},
        "console": {"()": "apps.common.logging.ConsoleFormatter"},
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "json" if LOG_FORMAT == "json" else "console",
            "filters": ["request_context", "redact"],
        },
    },
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    "loggers": {
        # Our access log covers every request; avoid duplicate 4xx/5xx lines from Django.
        "django.request": {"level": "ERROR", "propagate": True},
        "django.server": {"level": "WARNING", "propagate": True},
    },
}
