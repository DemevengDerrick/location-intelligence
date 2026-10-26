import sentry_sdk

from .base import *  # noqa: F403
from .base import env

DEBUG = False
ACCOUNT_EMAIL_VERIFICATION = "mandatory"

if PAYMENTS_DEMO_MODE:  # noqa: F405
    import logging

    logging.getLogger(__name__).warning("PAYMENTS_DEMO_MODE is on in production: no real payments.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
LANGUAGE_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

EMAIL_BACKEND = f"anymail.backends.{env('ANYMAIL_ESP', default='postmark')}.EmailBackend"
ANYMAIL = {
    "POSTMARK_SERVER_TOKEN": env("POSTMARK_SERVER_TOKEN", default=""),
    "RESEND_API_KEY": env("RESEND_API_KEY", default=""),
}

if dsn := env("SENTRY_DSN", default=""):
    sentry_sdk.init(dsn=dsn, send_default_pii=False, traces_sample_rate=0.1)
