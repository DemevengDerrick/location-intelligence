"""A local copy of the OpenStreetMap features the analysis needs, from the Cameroon extract.

Each refresh loads a new OsmImport beside the active one and switches over only when it is
complete, so analyses never see a half-loaded extract.
"""

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class ImportStatus(models.TextChoices):
    LOADING = "loading", _("Loading")
    ACTIVE = "active", _("Active")
    RETIRED = "retired", _("Retired")
    FAILED = "failed", _("Failed")


class OsmImport(TimeStampedModel):
    source_url = models.URLField(_("source"))
    data_timestamp = models.CharField(_("OSM data as of"), max_length=40, blank=True)
    status = models.CharField(
        _("status"), max_length=10, choices=ImportStatus.choices, default=ImportStatus.LOADING
    )
    counts = models.JSONField(_("features per category"), default=dict, blank=True)
    error = models.TextField(_("error"), blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    class Meta:
        verbose_name = _("OSM import")
        verbose_name_plural = _("OSM imports")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.data_timestamp or self.created_at:%Y-%m-%d} ({self.get_status_display()})"

    @classmethod
    def active(cls):
        return cls.objects.filter(status=ImportStatus.ACTIVE).order_by("-created_at").first()


class Category(models.TextChoices):
    BUILDING = "building", _("Building")
    WATERWAY = "waterway", _("River, stream or canal")
    WATER = "water", _("Water body")
    WETLAND = "wetland", _("Wetland")
    ROAD = "road", _("Road")
    SCHOOL = "school", _("School")
    HEALTH = "health", _("Health facility")
    MARKET = "market", _("Market")
    WATER_POINT = "water_point", _("Water point")
    PROTECTED = "protected", _("Protected area")
    POWER_LINE = "power_line", _("Power line")
    RAILWAY = "railway", _("Railway")
    COASTLINE = "coastline", _("Coastline")


class OsmFeature(models.Model):
    osm_import = models.ForeignKey(OsmImport, on_delete=models.CASCADE, related_name="features")
    category = models.CharField(max_length=12, choices=Category.choices)
    kind = models.CharField(max_length=40, blank=True)  # e.g. "hospital", "primary", "river"
    name = models.CharField(max_length=200, blank=True)
    paved = models.BooleanField(null=True)  # roads only
    osm_ref = models.CharField(max_length=24)  # "w123", "n456", "r789"
    geom = models.GeometryField(srid=4326)

    class Meta:
        indexes = [models.Index(fields=["osm_import", "category"])]

    def __str__(self):
        return f"{self.category} {self.name or self.osm_ref}"
