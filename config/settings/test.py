import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgis://app:app@localhost:5432/app")

from .base import *  # noqa: E402, F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_RATE_LIMITS = False
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_CLASSES": []}  # noqa: F405
# Rate limiting is exercised with the local-memory cache in tests.
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]
ADMIN_NOTIFICATION_EMAILS = ["ops@example.com"]
PAYMENTS_DEMO_MODE = True
STRIPE_SECRET_KEY = "sk_test_dummy"
STRIPE_WEBHOOK_SECRET = "whsec_test_dummy"
