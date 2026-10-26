"""Settings shared by every environment. Environment-specific overrides live in dev/test/prod."""

from pathlib import Path

import environ
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
SITE_NAME = env("SITE_NAME", default="Land Due Diligence")
SITE_URL = env("SITE_URL", default="http://localhost:8000")
SITE_ID = 1

INSTALLED_APPS = [
    # modeltranslation must come before django.contrib.admin
    "modeltranslation",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "django.contrib.postgres",
    "django.contrib.gis",
    # third party
    "rest_framework",
    "rest_framework_gis",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "django_celery_beat",
    "anymail",
    "storages",
    "django_ratelimit",
    # local apps, by domain
    "apps.core",
    "apps.accounts",
    "apps.orders",
    "apps.parcels",
    "apps.payments",
    "apps.analysis",
    "apps.reports",
    "apps.incidents",
    "apps.gazetteer",
    "apps.osm",
    "apps.partners",
    "apps.pricing",
    "apps.pages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
                "apps.pricing.context_processors.currency",
                "apps.pages.context_processors.public",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth -----------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
# URL names, so redirects resolve in the visitor's language (/fr/... or /en/...).
LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "portal:orders"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_ADAPTER = "apps.accounts.adapters.AccountAdapter"
DEV_MAILBOX_URL = env("DEV_MAILBOX_URL", default="http://localhost:8025")
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = env("ACCOUNT_EMAIL_VERIFICATION", default="optional")
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_RATE_LIMITS = {"login_failed": "10/m/ip,5/5m/key"}
# Google sign-in appears only once credentials are configured (no broken button before that).
if env("GOOGLE_CLIENT_ID", default=""):
    INSTALLED_APPS.append("allauth.socialaccount.providers.google")
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "APPS": [
            {
                "client_id": env("GOOGLE_CLIENT_ID", default=""),
                "secret": env("GOOGLE_CLIENT_SECRET", default=""),
            }
        ],
        "SCOPE": ["profile", "email"],
    }
}

# --- Internationalisation ---------------------------------------------------
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", _("French")), ("en", _("English"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
TIME_ZONE = "Africa/Douala"
USE_I18N = True
USE_TZ = True

MODELTRANSLATION_DEFAULT_LANGUAGE = "fr"
MODELTRANSLATION_LANGUAGES = ("fr", "en")

CURRENCIES = ["XAF", "CAD", "EUR", "USD"]

# --- Static and media -------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="app-private")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default=None)
# Where browsers reach the bucket, if different from the app (dev: localhost vs the s3 container).
AWS_S3_PUBLIC_ENDPOINT_URL = env("AWS_S3_PUBLIC_ENDPOINT_URL", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="auto")
AWS_DEFAULT_ACL = "private"
AWS_QUERYSTRING_AUTH = True  # files are only served through short-lived signed URLs
AWS_QUERYSTRING_EXPIRE = env.int("AWS_QUERYSTRING_EXPIRE", default=300)
AWS_S3_FILE_OVERWRITE = False

STORAGES = {
    "default": {"BACKEND": "apps.core.storage.PrivateS3Storage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

# --- Email ------------------------------------------------------------------
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@localhost")
# Staff addresses that receive new-lead and operational notifications.
ADMIN_NOTIFICATION_EMAILS = env.list("ADMIN_NOTIFICATION_EMAILS", default=[])
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))

# --- Payments ----------------------------------------------------------------------------
# Demo mode (NFR-18): every payment method goes through a fake checkout; no money moves.
PAYMENTS_DEMO_MODE = env.bool("PAYMENTS_DEMO_MODE", default=False)
DEMO_PAYMENT_SECRET = env("DEMO_PAYMENT_SECRET", default=SECRET_KEY)
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

# --- Maps and geocoding -------------------------------------------------------
# Esri World Imagery. Production needs an ArcGIS Location Platform key (ESRI_API_KEY), which
# switches to the keyed basemap endpoint; development uses the public tile service.
ESRI_API_KEY = env("ESRI_API_KEY", default="")
BASEMAP_TILE_URL = env(
    "BASEMAP_TILE_URL",
    default=(
        "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        if ESRI_API_KEY
        else "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
)
BASEMAP_ATTRIBUTION = env(
    "BASEMAP_ATTRIBUTION",
    default="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
)
NOMINATIM_URL = env("NOMINATIM_URL", default="https://nominatim.openstreetmap.org")
# Comma-separated Overpass servers, tried in order (the public ones are often busy).
OVERPASS_URL = env(
    "OVERPASS_URL",
    default="https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter",
)
# Local OpenStreetMap copy (apps.osm): the Geofabrik extract, refreshed weekly
OSM_EXTRACT_URL = env(
    "OSM_EXTRACT_URL", default="https://download.geofabrik.de/africa/cameroon-latest.osm.pbf"
)
OSM_DATA_DIR = env("OSM_DATA_DIR", default="/data/osm")
# WorldPop age-sex rasters (manage.py load_worldpop)
WORLDPOP_DATA_DIR = env("WORLDPOP_DATA_DIR", default="/data/worldpop")
# GHSL built-up tiles for Cameroon (manage.py load_ghsl); shares the population volume
GHSL_DATA_DIR = env("GHSL_DATA_DIR", default="/data/worldpop/ghsl")
# Routing engine (Valhalla) for travel times and isochrones
VALHALLA_URL = env("VALHALLA_URL", default="http://valhalla:8002")
# Shared report links (FR-19): expiry choices offered to the customer, in days
REPORT_SHARE_DAYS = [7, 30, 90]
REPORT_SHARE_DEFAULT_DAYS = 30
NOMINATIM_USER_AGENT = env(
    "NOMINATIM_USER_AGENT",
    default=f"{SITE_NAME} (contact: {env('DEFAULT_FROM_EMAIL', default='')})",
)

# --- REST framework ---------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min"},
}

# --- Celery -----------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# django-ratelimit works with Django's Redis cache (atomic incr) but doesn't list it officially.
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.W001"]

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
