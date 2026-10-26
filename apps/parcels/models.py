from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.orders.models import Order

from .choices import InputMethod
from .geometry import area_m2

__all__ = ["InputMethod", "Parcel", "ParcelGeometryHistory"]


class Parcel(TimeStampedModel):
    order = models.ForeignKey(
        Order, verbose_name=_("order"), on_delete=models.CASCADE, related_name="parcels"
    )
    geometry = models.MultiPolygonField(_("boundary"), srid=4326, null=True, blank=True)
    input_method = models.CharField(_("input method"), max_length=16, choices=InputMethod.choices)
    is_approximate = models.BooleanField(
        _("approximate location"),
        default=False,
        help_text=_("Pin-only orders are analysed with a default buffer (FR-9)."),
    )
    stated_area_m2 = models.FloatField(_("seller-stated area (m²)"), null=True, blank=True)
    computed_area_m2 = models.FloatField(_("computed area (m²)"), null=True, blank=True)
    quartier = models.CharField(_("quartier"), max_length=200, blank=True)
    commune = models.CharField(_("commune"), max_length=200, blank=True)
    region = models.CharField(_("region"), max_length=100, blank=True)
    title_number = models.CharField(
        _("land title number"),
        max_length=100,
        blank=True,
        help_text=_("Stored as given by the customer. Never verified."),
    )

    class Meta:
        verbose_name = _("parcel")
        verbose_name_plural = _("parcels")

    def __str__(self):
        return f"{self.order} · {self.quartier or self.commune or self.pk}"

    def save(self, *args, **kwargs):
        # Pin-only parcels are a buffer around a point (FR-9): there is no real area to report.
        measurable = self.geometry is not None and not self.is_approximate
        self.computed_area_m2 = area_m2(self.geometry) if measurable else None
        super().save(*args, **kwargs)


class ParcelGeometryHistory(models.Model):
    """Previous boundaries, kept whenever an analyst saves a new one (FR-40)."""

    parcel = models.ForeignKey(
        Parcel, verbose_name=_("parcel"), on_delete=models.CASCADE, related_name="geometry_history"
    )
    geometry = models.MultiPolygonField(_("boundary"), srid=4326)
    input_method = models.CharField(_("input method"), max_length=16, choices=InputMethod.choices)
    replaced_at = models.DateTimeField(_("replaced at"), auto_now_add=True)
    replaced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("replaced by"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("geometry history entry")
        verbose_name_plural = _("geometry history")
        ordering = ["-replaced_at"]

    def __str__(self):
        return f"{self.parcel} @ {self.replaced_at:%Y-%m-%d}"
