import logging

import httpx
from celery import shared_task
from django.utils import timezone

from apps.core import llm

from . import collectors, extraction
from .area_search import _gdelt_source
from .config import signals_settings
from .models import Source, SourceItem, SourceType

logger = logging.getLogger(__name__)

EXTRACT_BATCH = 50  # items extracted per daily run, to keep the LLM bill predictable


@shared_task(time_limit=60 * 60, acks_late=True)
def collect_sources():
    """Daily (django-celery-beat), FR-22: read the outlets' feeds and a national GDELT search,
    keep the land-related items, then extract incidents from new items."""
    settings = signals_settings()
    http = collectors.client()
    created = {}
    now = timezone.now()
    for source in Source.objects.filter(is_active=True, source_type=SourceType.RSS):
        if source.last_crawled_at and (now - source.last_crawled_at).total_seconds() < (
            source.crawl_frequency_hours * 3600 - 600  # a little slack for beat's timing
        ):
            continue
        try:
            created[source.name] = collectors.collect_source(
                source, settings.keywords, http, settings.weak_keywords
            )
        except (httpx.HTTPError, ValueError, SyntaxError) as exc:
            logger.warning("Collecting %s failed: %r", source.name, exc)
    if settings.gdelt_enabled:
        created["GDELT"] = _collect_gdelt(settings, http)
    if llm.available():
        extract_pending.delay()
    return created


def _collect_gdelt(settings, http):
    try:
        query = collectors.gdelt_query(["Cameroun", "Cameroon"], settings.gdelt_keywords)
        gdelt = _gdelt_source()
        count = 0
        for entry in collectors.gdelt_search(query, "1week", 250, http):
            if collectors.relevant(entry, settings.keywords, settings.weak_keywords):
                count += collectors.store(entry, gdelt)[1]
        gdelt.last_crawled_at = timezone.now()
        gdelt.save(update_fields=["last_crawled_at", "updated_at"])
        return count
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GDELT national search failed: %r", exc)
        return None


@shared_task(acks_late=True)
def extract_pending(limit=EXTRACT_BATCH):
    ids = list(
        SourceItem.objects.filter(extracted_at__isnull=True)
        .order_by("-published_at")
        .values_list("pk", flat=True)[:limit]
    )
    return extract_items(ids)


@shared_task(acks_late=True, time_limit=30 * 60)
def extract_items(item_ids):
    """Extract incidents from these items (skipping any already extracted)."""
    made = 0
    for item in SourceItem.objects.filter(pk__in=item_ids, extracted_at__isnull=True):
        try:
            made += len(extraction.extract_item(item))
        except llm.LlmUnavailable:
            return made
        except Exception as exc:  # one bad item never blocks the rest
            logger.exception("Extraction failed for item %s", item.pk)
            item.extraction_error = repr(exc)[:1000]
            item.save(update_fields=["extraction_error", "updated_at"])
    return made
