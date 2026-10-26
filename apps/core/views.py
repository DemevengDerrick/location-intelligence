import logging

import redis
from django.conf import settings
from django.core.files.storage import default_storage
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache

logger = logging.getLogger(__name__)


def _check_db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT PostGIS_Version()")


def _check_redis():
    redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2).ping()


def _check_storage():
    connection = getattr(default_storage, "connection", None)
    if connection is not None:
        # exists() just answers False when the whole bucket is missing; check the bucket.
        connection.meta.client.head_bucket(Bucket=default_storage.bucket_name)
    else:
        default_storage.exists("healthcheck")


@never_cache
def health(request):
    checks = {"db": _check_db, "redis": _check_redis, "storage": _check_storage}
    result = {}
    for name, check in checks.items():
        try:
            check()
            result[name] = "ok"
        except Exception:
            logger.exception("Health check %s failed", name)
            result[name] = "error"
    status = 200 if all(v == "ok" for v in result.values()) else 503
    return JsonResponse(result, status=status)
