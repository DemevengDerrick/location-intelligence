from celery import shared_task
from django.conf import settings

from . import loader


@shared_task(time_limit=3 * 60 * 60, acks_late=True)
def refresh_osm():
    """Weekly (django-celery-beat): download the extract and switch to it once loaded."""
    osm_import = loader.load(loader.download(), source_url=settings.OSM_EXTRACT_URL)
    return osm_import.counts
