import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.orders.models import Order


class Report(TimeStampedModel):
    reference = models.UUIDField(_("report ID"), default=uuid.uuid4, unique=True, editable=False)
    order = models.OneToOneField(
        Order, verbose_name=_("order"), on_delete=models.PROTECT, related_name="report"
    )
    run = models.ForeignKey(
        "analysis.AnalysisRun",
        verbose_name=_("analysis run"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    draft = models.JSONField(
        _("draft"),
        default=dict,
        blank=True,
        help_text=_("Findings as edited by the analyst, before approval."),
    )

    class Meta:
        verbose_name = _("report")
        verbose_name_plural = _("reports")

    def __str__(self):
        return str(self.reference)[:8]

    @property
    def latest_number(self):
        return self.versions.aggregate(models.Max("number"))["number__max"] or 0


class ReportVersion(TimeStampedModel):
    """A locked, delivered version. Changes after delivery create a new version (FR-44)."""

    report = models.ForeignKey(
        Report, verbose_name=_("report"), on_delete=models.CASCADE, related_name="versions"
    )
    number = models.PositiveIntegerField(_("version"))
    language = models.CharField(_("language"), max_length=5, choices=settings.LANGUAGES)
    content = models.JSONField(_("content"), default=dict)
    pdf = models.FileField(_("PDF"), upload_to="reports/%Y/%m/", blank=True)
    sha256 = models.CharField(_("SHA-256"), max_length=64, blank=True, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("approved by"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)

    class Meta:
        verbose_name = _("report version")
        verbose_name_plural = _("report versions")
        ordering = ["report", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "number", "language"], name="unique_report_version_language"
            )
        ]

    def __str__(self):
        return f"{self.report} v{self.number} ({self.language})"


def _share_token():
    import secrets

    return secrets.token_urlsafe(24)


class ReportShare(TimeStampedModel):
    """A read-only link to the latest delivered report, with an expiry date (FR-19). The
    customer can revoke it at any time; views are counted."""

    report = models.ForeignKey(
        Report, verbose_name=_("report"), on_delete=models.CASCADE, related_name="shares"
    )
    token = models.CharField(_("token"), max_length=64, unique=True, default=_share_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    expires_at = models.DateTimeField(_("expires at"))
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)
    views = models.PositiveIntegerField(_("views"), default=0)
    last_viewed_at = models.DateTimeField(_("last viewed at"), null=True, blank=True)

    class Meta:
        verbose_name = _("shared report link")
        verbose_name_plural = _("shared report links")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.report} → {self.expires_at:%Y-%m-%d}"

    @property
    def is_active(self):
        from django.utils import timezone

        return self.revoked_at is None and self.expires_at > timezone.now()
