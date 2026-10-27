from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class PlaceType(models.TextChoices):
    COUNTRY = "country", _("Country")
    REGION = "region", _("Region")
    DEPARTMENT = "department", _("Department")
    ARRONDISSEMENT = "arrondissement", _("Arrondissement")
    COMMUNE = "commune", _("Commune")
    QUARTIER = "quartier", _("Quartier")
    VILLAGE = "village", _("Village")
    LIEU_DIT = "lieu_dit", _("Lieu-dit")


class GazetteerPlace(TimeStampedModel):
    name = models.CharField(_("name"), max_length=200, db_index=True)
    aliases = ArrayField(
        models.CharField(max_length=200), verbose_name=_("aliases"), default=list, blank=True
    )
    place_type = models.CharField(_("type"), max_length=16, choices=PlaceType.choices)
    geometry = models.GeometryField(_("geometry"), srid=4326)
    region = models.CharField(_("region"), max_length=100, blank=True)
    department = models.CharField(_("department"), max_length=100, blank=True)
    arrondissement = models.CharField(_("arrondissement"), max_length=100, blank=True)
    commune = models.CharField(_("commune"), max_length=100, blank=True)
    source = models.CharField(_("source"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("gazetteer place")
        verbose_name_plural = _("gazetteer")
        ordering = ["name"]
        indexes = [GinIndex(fields=["aliases"], name="gazetteer_aliases_gin")]

    def __str__(self):
        return f"{self.name} ({self.get_place_type_display()})"


class ReferenceLayerKind(models.TextChoices):
    DUP_CORRIDOR = "dup_corridor", _("Public-utility (DUP) zone")
    INFRASTRUCTURE = "infrastructure", _("Infrastructure corridor")
    PROTECTED_AREA = "protected_area", _("Protected area")
    FOREST_ESTATE = "forest_estate", _("Permanent forest estate")
    CONCESSION = "concession", _("Land-use concession")
    RISK_ZONE = "risk_zone", _("Custom risk zone")


class ReferenceLayer(TimeStampedModel):
    """Admin-maintained constraint features (FR-50). Setback rules live in SiteSetting."""

    kind = models.CharField(_("kind"), max_length=20, choices=ReferenceLayerKind.choices)
    name = models.CharField(_("name"), max_length=200)
    geometry = models.GeometryField(_("geometry"), srid=4326)
    properties = models.JSONField(_("properties"), default=dict, blank=True)
    source = models.CharField(_("source"), max_length=200, blank=True)
    valid_from = models.DateField(_("valid from"), null=True, blank=True)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("reference layer feature")
        verbose_name_plural = _("reference layers")
        ordering = ["kind", "name"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"
