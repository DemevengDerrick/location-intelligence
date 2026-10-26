from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class AuditLog(models.Model):
    """Append-only record of logins, payments, status changes, approvals, admin edits (NFR-10)."""

    created_at = models.DateTimeField(_("created at"), auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("actor"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(_("action"), max_length=64, db_index=True)
    target_type = models.ForeignKey(
        ContentType, verbose_name=_("target type"), null=True, blank=True, on_delete=models.SET_NULL
    )
    target_id = models.CharField(_("target id"), max_length=64, blank=True)
    data = models.JSONField(_("data"), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)

    class Meta:
        verbose_name = _("audit log entry")
        verbose_name_plural = _("audit log")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class SiteSetting(TimeStampedModel):
    """Admin-editable configuration: prices, rating thresholds, setback rules, keyword lists."""

    key = models.SlugField(_("key"), max_length=100, unique=True)
    value = models.JSONField(_("value"), default=dict)
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("setting")
        verbose_name_plural = _("settings")
        ordering = ["key"]

    def __str__(self):
        return self.key


class Dataset(TimeStampedModel):
    """Licence and attribution for each data source; the report's Sources section reads this."""

    slug = models.SlugField(_("slug"), max_length=100, unique=True)
    name = models.CharField(_("name"), max_length=200)
    provider = models.CharField(_("provider"), max_length=200, blank=True)
    version = models.CharField(_("version"), max_length=100, blank=True)
    licence = models.CharField(_("licence"), max_length=200)
    attribution = models.TextField(_("attribution"))
    url = models.URLField(_("URL"), blank=True)
    commercial_use_allowed = models.BooleanField(_("commercial use allowed"), default=False)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("dataset")
        verbose_name_plural = _("datasets")
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} {self.version}".strip()
