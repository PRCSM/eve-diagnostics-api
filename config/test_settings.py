"""Settings for the test suite: production-like (DEBUG off) with fast hashing and fixed secrets."""

import os

os.environ.setdefault("DJANGO_DEBUG", "false")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
os.environ.setdefault("JWT_SIGNING_KEY", "test-only-jwt-signing-key-with-enough-length")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test-only-webhook-secret")
os.environ.setdefault("POSTGRES_PASSWORD", "eve-dev-password")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from config.settings import *  # noqa: E402,F403
from config.settings import DATABASES  # noqa: E402

# Fast (insecure) hashing keeps the suite quick; never used outside tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Threads in concurrency tests each open their own connection; don't keep them around.
DATABASES["default"]["CONN_MAX_AGE"] = 0

ALLOWED_HOSTS = ["testserver", "localhost"]
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Static files aren't collected for tests; drop WhiteNoise and use plain storage.
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise.")]  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
