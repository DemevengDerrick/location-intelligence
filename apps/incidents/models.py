from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class SourceType(models.TextChoices):
    RSS = "rss", _("RSS feed")
    PAGE = "page", _("Web page")
    NEWS_ALERT = "news_alert", _("News search alert")
    GAZETTE = "gazette", _("Official gazette or communiqué")
    MANUAL = "manual", _("Manual")


class Source(TimeStampedModel):
    name = models.CharField(_("name"), max_length=200)
    url = models.URLField(_("URL"), max_length=500)
    source_type = models.CharField(_("type"), max_length=16, choices=SourceType.choices)
    language = models.CharField(_("language"), max_length=5, choices=settings.LANGUAGES)
    search_url = models.CharField(
        _("search feed URL"),
        max_length=500,
        blank=True,
        help_text=_(
            "Optional feed of the outlet's own search, with {query} where the search words go "
            "(e.g. https://example.cm/?s={query}&feed=rss2). Used for area searches when the "
            "site's robots.txt allows it."
        ),
    )
    crawl_frequency_hours = models.PositiveIntegerField(_("crawl frequency (hours)"), default=24)
    is_active = models.BooleanField(_("active"), default=True)
    last_crawled_at = models.DateTimeField(_("last crawled at"), null=True, blank=True)

    class Meta:
        verbose_name = _("source")
        verbose_name_plural = _("sources")
        ordering = ["name"]

    def __str__(self):
        return self.name


class SourceItem(TimeStampedModel):
    source = models.ForeignKey(
        Source,
        verbose_name=_("source"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items",
    )
    url = models.URLField(_("URL"), max_length=1000)
    title = models.CharField(_("title"), max_length=500)
    outlet = models.CharField(_("outlet"), max_length=200, blank=True)
    published_at = models.DateTimeField(_("published at"), null=True, blank=True)
    retrieved_at = models.DateTimeField(_("retrieved at"), auto_now_add=True)
    content_hash = models.CharField(_("content hash"), max_length=64, unique=True)
    private_text = models.TextField(
        _("full text (private)"), blank=True, help_text=_("Never shown to customers (FR-25).")
    )
    language = models.CharField(_("language"), max_length=5, blank=True)
    extracted_at = models.DateTimeField(_("extracted at"), null=True, blank=True)
    extraction_error = models.TextField(_("extraction error"), blank=True)

    class Meta:
        verbose_name = _("source item")
        verbose_name_plural = _("source items")
        ordering = ["-published_at"]

    def __str__(self):
        return self.title


class IncidentType(models.TextChoices):
    """FR-27."""

    TITLE_CANCELLATION = "title_cancellation", _("Title cancellation or withdrawal")
    EXPROPRIATION = "expropriation", _("Expropriation or public-utility declaration")
    DEMOLITION = "demolition", _("Demolition or eviction campaign")
    DOUBLE_SALE = "double_sale", _("Double sale or fraud allegation")
    BOUNDARY_DISPUTE = "boundary_dispute", _("Boundary or inheritance dispute")
    CUSTOMARY_CONFLICT = "customary_conflict", _("Customary versus registered land conflict")
    PUBLIC_LAND_ENCROACHMENT = "public_land", _("Encroachment on public land")
    OTHER = "other", _("Other")


class LocationPrecision(models.TextChoices):
    """FR-29. Ordered from most to least precise."""

    POINT = "point", _("Point")
    QUARTIER = "quartier", _("Quartier")
    COMMUNE = "commune", _("Commune")
    DEPARTMENT = "department", _("Department")
    REGION = "region", _("Region")


class ReviewStatus(models.TextChoices):
    UNREVIEWED = "unreviewed", _("Unreviewed")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    MERGED = "merged", _("Merged into another incident")


class Incident(TimeStampedModel):
    incident_type = models.CharField(_("type"), max_length=32, choices=IncidentType.choices)
    event_date = models.DateField(_("event date"), null=True, blank=True)
    # Translated into summary_fr / summary_en by modeltranslation (see translation.py).
    summary = models.TextField(_("neutral summary"), blank=True)
    place_names = models.JSONField(_("place names mentioned"), default=list, blank=True)
    geometry = models.GeometryField(_("location"), srid=4326, null=True, blank=True)
    place = models.ForeignKey(
        "gazetteer.GazetteerPlace",
        verbose_name=_("place"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incidents",
        help_text=_("The gazetteer place the incident was located at, when it is an area."),
    )
    precision = models.CharField(
        _("location precision"), max_length=16, choices=LocationPrecision.choices, blank=True
    )
    is_official_act = models.BooleanField(_("official act"), default=False)
    confidence = models.FloatField(_("extraction confidence"), null=True, blank=True)
    review_status = models.CharField(
        _("review status"),
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.UNREVIEWED,
        db_index=True,
    )
    merged_into = models.ForeignKey(
        "self",
        verbose_name=_("merged into"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="merged_duplicates",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("reviewed by"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    sources = models.ManyToManyField(
        SourceItem, verbose_name=_("sources"), through="IncidentSource", related_name="incidents"
    )

    class Meta:
        verbose_name = _("incident")
        verbose_name_plural = _("incidents")
        ordering = ["-event_date"]

    def __str__(self):
        return f"{self.get_incident_type_display()} · {self.event_date or '?'}"


class IncidentSource(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE)
    source_item = models.ForeignKey(SourceItem, on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("incident source")
        verbose_name_plural = _("incident sources")
        constraints = [
            models.UniqueConstraint(
                fields=["incident", "source_item"], name="unique_incident_source"
            )
        ]

    def __str__(self):
        return f"{self.incident_id} ← {self.source_item_id}"


class SearchProvider(models.TextChoices):
    GDELT = "gdelt", _("GDELT news index")
    OUTLETS = "outlets", _("Outlet search feeds")


class AreaSearch(TimeStampedModel):
    """The last news search for one place and provider. Reports reuse it while it is recent
    (SiteSetting "area_signals" max_age_days) instead of searching again."""

    place = models.ForeignKey(
        "gazetteer.GazetteerPlace",
        verbose_name=_("place"),
        on_delete=models.CASCADE,
        related_name="area_searches",
    )
    provider = models.CharField(_("provider"), max_length=10, choices=SearchProvider.choices)
    query = models.TextField(_("query"), blank=True)
    searched_at = models.DateTimeField(_("searched at"), null=True, blank=True)
    ok = models.BooleanField(_("succeeded"), default=False)
    error = models.TextField(_("error"), blank=True)
    items = models.ManyToManyField(
        SourceItem, verbose_name=_("items found"), blank=True, related_name="area_searches"
    )

    class Meta:
        verbose_name = _("area search")
        verbose_name_plural = _("area searches")
        ordering = ["-searched_at"]
        constraints = [
            models.UniqueConstraint(fields=["place", "provider"], name="one_search_per_place")
        ]

    def __str__(self):
        return f"{self.place} · {self.get_provider_display()}"


class UnmatchedPlace(TimeStampedModel):
    """A place name from an article that the gazetteer does not know (FR-28). An analyst maps
    it to a gazetteer place, which adds the name as an alias and locates its incidents."""

    name = models.CharField(_("name"), max_length=200, unique=True)
    occurrences = models.PositiveIntegerField(_("occurrences"), default=1)
    example = models.ForeignKey(
        SourceItem,
        verbose_name=_("example item"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    resolved_place = models.ForeignKey(
        "gazetteer.GazetteerPlace",
        verbose_name=_("mapped to"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    ignored = models.BooleanField(
        _("ignore"), default=False, help_text=_("Not a place in Cameroon, or too vague.")
    )

    class Meta:
        verbose_name = _("unmatched place name")
        verbose_name_plural = _("unmatched place names")
        ordering = ["-occurrences", "name"]

    def __str__(self):
        return self.name
