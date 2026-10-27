"""Turn a collected item into structured incidents (FR-26, FR-27, FR-31).

The extractor reads the item's private text (title and feed description) and returns zero
or more incidents. Incidents start unreviewed (FR-30); nothing reaches a customer before an
analyst approves it."""

from datetime import date
from typing import Literal, Protocol

from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, Field

from apps.core import llm

from . import geocode
from .models import Incident, IncidentSource, IncidentType, SourceItem

MAX_SUMMARY_WORDS = 40

SYSTEM = """You extract land-issue incidents in Cameroon from news items, for a land \
due-diligence service. An incident is a reported event about land: a land title cancelled or \
withdrawn; an expropriation or a declaration of public utility; a demolition or eviction \
campaign; a double sale or land fraud allegation; a boundary or inheritance dispute; a conflict \
between customary and registered land rights; encroachment on public land; or another land \
issue.

Rules:
- Return no incident when the item is not about a concrete land issue in Cameroon (general \
economy, politics, opinion, or land policy without a specific case).
- place_names: the places in Cameroon where the event happened, as written in the item \
(quartier, village, lieu-dit, commune, town, department or region). Most precise first. Do not \
include the country.
- event_date: when the event happened, as YYYY-MM-DD, YYYY-MM or YYYY. If unknown, use the \
publication date given with the item.
- summary_fr and summary_en: a short, neutral summary in French and in English, at most 40 words \
each, written fresh (never copied). State facts as reported ("selon ...", "reportedly"). Never \
name private individuals: replace them with a role ("un héritier", "a buyer", "residents"). \
Public bodies, companies acting officially, and officials acting in office may be named.
- is_official_act: true only for an official decision or notice (decree, order, public-utility \
declaration, title cancellation by the ministry, official demolition notice).
- confidence: from 0 to 1, how sure you are that this is a real land incident at those places."""


class ExtractedIncident(BaseModel):
    incident_type: Literal[tuple(IncidentType.values)]  # type: ignore[valid-type]
    place_names: list[str]
    event_date: str = Field(description="YYYY-MM-DD, YYYY-MM or YYYY")
    summary_fr: str
    summary_en: str
    is_official_act: bool
    confidence: float


class Extraction(BaseModel):
    incidents: list[ExtractedIncident]


class Extractor(Protocol):
    def extract(self, item: SourceItem) -> Extraction: ...


class ClaudeExtractor:
    def extract(self, item):
        published = item.published_at.date().isoformat() if item.published_at else "unknown"
        prompt = (
            f"Outlet: {item.outlet}\nPublished: {published}\nURL: {item.url}\n\n"
            f"<item>\n{item.private_text or item.title}\n</item>"
        )
        return llm.parse(system=SYSTEM, prompt=prompt, schema=Extraction)


def extractor() -> Extractor | None:
    """The configured extractor, or None until ANTHROPIC_API_KEY is set."""
    return ClaudeExtractor() if llm.available() else None


def parse_date(value):
    parts = (value or "").strip()[:10].split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def shorten(text, words=MAX_SUMMARY_WORDS):
    parts = text.split()
    return text.strip() if len(parts) <= words else " ".join(parts[:words]) + " …"


def extract_item(item, extractor_=None, fallback_place=None):
    """Create unreviewed incidents from one item; returns them. Errors are stored on the
    item, and the item can be extracted again later."""
    extractor_ = extractor_ or extractor()
    if extractor_ is None:
        raise llm.LlmUnavailable("ANTHROPIC_API_KEY is not set")
    try:
        result = extractor_.extract(item)
    except llm.LlmRefused as exc:
        item.extraction_error = f"Refused: {exc}"
        item.extracted_at = timezone.now()
        item.save(update_fields=["extraction_error", "extracted_at", "updated_at"])
        return []
    if fallback_place is None:
        search = item.area_searches.select_related("place").order_by("-searched_at").first()
        fallback_place = search.place if search else None
    created = []
    with transaction.atomic():
        for found in result.incidents:
            incident = Incident(
                incident_type=found.incident_type,
                event_date=parse_date(found.event_date)
                or (item.published_at.date() if item.published_at else None),
                summary_fr=shorten(found.summary_fr),
                summary_en=shorten(found.summary_en),
                summary=shorten(found.summary_fr),
                place_names=[n.strip() for n in found.place_names if n.strip()][:10],
                is_official_act=found.is_official_act,
                confidence=max(0.0, min(1.0, found.confidence)),
            )
            geocode.locate(incident, item, fallback_place)
            incident.save()
            IncidentSource.objects.create(incident=incident, source_item=item)
            created.append(incident)
        item.extracted_at = timezone.now()
        item.extraction_error = ""
        item.save(update_fields=["extracted_at", "extraction_error", "updated_at"])
    return created
