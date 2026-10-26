from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Currency
from apps.core.models import TimeStampedModel
from apps.orders.models import Order


class Profession(models.TextChoices):
    SURVEYOR = "surveyor", _("Surveyor (géomètre)")
    NOTARY = "notary", _("Notary")


class PartnerStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")
    PENDING = "pending", _("Pending vetting")


class Partner(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user account"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="partner_profile",
    )
    name = models.CharField(_("name"), max_length=200)
    profession = models.CharField(_("profession"), max_length=16, choices=Profession.choices)
    registration_number = models.CharField(_("registration number"), max_length=100, blank=True)
    regions = ArrayField(
        models.CharField(max_length=100), verbose_name=_("regions covered"), default=list
    )
    rate_amount = models.DecimalField(
        _("rate"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    rate_currency = models.CharField(
        _("rate currency"), max_length=3, choices=Currency.choices, default=Currency.XAF
    )
    status = models.CharField(
        _("status"), max_length=16, choices=PartnerStatus.choices, default=PartnerStatus.PENDING
    )
    phone = models.CharField(_("phone"), max_length=32, blank=True)
    email = models.EmailField(_("email"), blank=True)

    class Meta:
        verbose_name = _("partner")
        verbose_name_plural = _("partners")
        ordering = ["name"]

    def __str__(self):
        return self.name


class FieldJobStatus(models.TextChoices):
    OFFERED = "offered", _("Offered")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    SUBMITTED = "submitted", _("Findings submitted")
    COMPLETED = "completed", _("Completed")


class PayoutStatus(models.TextChoices):
    UNPAID = "unpaid", _("Unpaid")
    PAID = "paid", _("Paid")


class FieldJob(TimeStampedModel):
    order = models.ForeignKey(
        Order, verbose_name=_("order"), on_delete=models.PROTECT, related_name="field_jobs"
    )
    partner = models.ForeignKey(
        Partner, verbose_name=_("partner"), on_delete=models.PROTECT, related_name="jobs"
    )
    brief = models.TextField(_("brief"), blank=True)
    checklist = models.JSONField(_("checklist"), default=list, blank=True)
    due_date = models.DateField(_("due date"), null=True, blank=True)
    status = models.CharField(
        _("status"), max_length=16, choices=FieldJobStatus.choices, default=FieldJobStatus.OFFERED
    )
    fee_amount = models.DecimalField(
        _("fee"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    fee_currency = models.CharField(
        _("fee currency"), max_length=3, choices=Currency.choices, default=Currency.XAF
    )
    payout_status = models.CharField(
        _("payout status"), max_length=8, choices=PayoutStatus.choices, default=PayoutStatus.UNPAID
    )

    class Meta:
        verbose_name = _("field job")
        verbose_name_plural = _("field jobs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order} · {self.partner}"


class ObservationKind(models.TextChoices):
    PHOTO = "photo", _("Photo")
    BOUNDARY_MARKER = "boundary_marker", _("Boundary marker")
    OCCUPANCY = "occupancy", _("Occupancy observation")
    ACCESS = "access", _("Access observation")
    NEIGHBOUR_STATEMENT = "neighbour_statement", _("Neighbour statement")
    REGISTRY_SEARCH = "registry_search", _("Registry search result")


class FieldObservation(TimeStampedModel):
    job = models.ForeignKey(
        FieldJob, verbose_name=_("field job"), on_delete=models.CASCADE, related_name="observations"
    )
    kind = models.CharField(_("kind"), max_length=24, choices=ObservationKind.choices)
    location = models.PointField(_("location"), srid=4326, null=True, blank=True)
    taken_at = models.DateTimeField(_("taken at"), null=True, blank=True)
    file = models.FileField(_("file"), upload_to="field/%Y/%m/", blank=True)
    notes = models.TextField(_("notes"), blank=True)
    distance_from_parcel_m = models.FloatField(_("distance from parcel (m)"), null=True, blank=True)

    class Meta:
        verbose_name = _("field observation")
        verbose_name_plural = _("field observations")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.job}"
