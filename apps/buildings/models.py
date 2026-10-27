"""A local copy of the Google Open Buildings footprints for Cameroon (manage.py load_buildings).

Like the OSM copy, each load is a new release beside the active one, switched over only when
complete, so analyses never see a half-loaded set.
"""

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class ReleaseStatus(models.TextChoices):
    LOADING = "loading", _("Loading")
    ACTIVE = "active", _("Active")
    RETIRED = "retired", _("Retired")
    FAILED = "failed", _("Failed")


class BuildingRelease(TimeStampedModel):
    version = models.CharField(_("version"), max_length=40)  # e.g. "v3"
    source_url = models.CharField(_("source"), max_length=500)
    status = models.CharField(
        _("status"), max_length=10, choices=ReleaseStatus.choices, default=ReleaseStatus.LOADING
    )
    count = models.PositiveIntegerField(_("buildings"), default=0)
    error = models.TextField(_("error"), blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    class Meta:
        verbose_name = _("building release")
        verbose_name_plural = _("building releases")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.version} {self.created_at:%Y-%m-%d} ({self.get_status_display()})"

    @classmethod
    def active(cls):
        return cls.objects.filter(status=ReleaseStatus.ACTIVE).order_by("-created_at").first()


class Building(models.Model):
    release = models.ForeignKey(BuildingRelease, on_delete=models.CASCADE, related_name="+")
    geom = models.PolygonField(srid=4326)
    area_m2 = models.FloatField()
    confidence = models.FloatField()  # the model's score, 0.65–1 in v3
    plus_code = models.CharField(max_length=16, blank=True)

    class Meta:
        indexes = [models.Index(fields=["release"])]

    def __str__(self):
        return self.plus_code or str(self.pk)
