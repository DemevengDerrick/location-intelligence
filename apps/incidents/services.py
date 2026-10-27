"""Analyst review of incidents (FR-30, FR-31) and the admin map's filters (FR-35)."""

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from . import geocode
from .models import Incident, IncidentSource, IncidentType, ReviewStatus


def approve(queryset, analyst):
    """Approve after the analyst confirmed the summaries name no private individual."""
    return queryset.exclude(review_status=ReviewStatus.MERGED).update(
        review_status=ReviewStatus.APPROVED, reviewed_by=analyst, reviewed_at=timezone.now()
    )


@transaction.atomic
def merge(queryset, analyst):
    """Keep the oldest incident; the others become duplicates and give it their sources."""
    incidents = list(queryset.order_by("created_at"))
    kept, duplicates = incidents[0], incidents[1:]
    for duplicate in duplicates:
        for link in IncidentSource.objects.filter(incident=duplicate):
            IncidentSource.objects.get_or_create(incident=kept, source_item_id=link.source_item_id)
        duplicate.review_status = ReviewStatus.MERGED
        duplicate.merged_into = kept
        duplicate.reviewed_by, duplicate.reviewed_at = analyst, timezone.now()
        duplicate.save()
        kept.is_official_act = kept.is_official_act or duplicate.is_official_act
    kept.save()
    return kept


def incident_from_item(item):
    """An empty unreviewed incident linked to the item, placed at the area searched, for an
    analyst to complete by hand (when no LLM is configured)."""
    search = item.area_searches.select_related("place").order_by("-searched_at").first()
    incident = Incident(
        incident_type=IncidentType.OTHER,
        event_date=item.published_at.date() if item.published_at else None,
    )
    if search:
        incident.place_names = [search.place.name]
        geocode.locate(incident, item, search.place)
    incident.save()
    IncidentSource.objects.create(incident=incident, source_item=item)
    return incident


def filtered(params):
    incidents = Incident.objects.filter(geometry__isnull=False)
    if params.get("type"):
        incidents = incidents.filter(incident_type=params["type"])
    if params.get("status"):
        incidents = incidents.filter(review_status=params["status"])
    if start := parse_date(params.get("from") or ""):
        incidents = incidents.filter(event_date__gte=start)
    if end := parse_date(params.get("to") or ""):
        incidents = incidents.filter(event_date__lte=end)
    return incidents
