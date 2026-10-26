"""Read admin-editable SiteSetting values, cached briefly so pages don't hit the DB each time."""

from django.core.cache import cache

from .models import SiteSetting

_CACHE_PREFIX = "site_setting:"
_TTL = 60
_MISSING = object()


def get_setting(key, default=None):
    cache_key = _CACHE_PREFIX + key
    value = cache.get(cache_key, _MISSING)
    if value is _MISSING:
        value = SiteSetting.objects.filter(key=key).values_list("value", flat=True).first()
        cache.set(cache_key, value, _TTL)
    return default if value is None else value


def clear_setting_cache(key):
    cache.delete(_CACHE_PREFIX + key)
