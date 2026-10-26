from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.parcels.models import Parcel


class RunStatus(models.TextChoices):
    QUEUED = "queued", _("Queued")
    RUNNING = "running", _("Running")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")


class ModuleStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    OK = "ok", _("OK")
    WARNING = "warning", _("Warning")
    FAILED = "failed", _("Failed")


class Rating(models.TextChoices):
    GREEN = "green", _("Green")
    AMBER = "amber", _("Amber")
    RED = "red", _("Red")
    GREY = "grey", _("Unknown")


class AnalysisRun(TimeStampedModel):
    parcel = models.ForeignKey(
        Parcel, verbose_name=_("parcel"), on_delete=models.CASCADE, related_name="analysis_runs"
    )
    status = models.CharField(
        _("status"), max_length=16, choices=RunStatus.choices, default=RunStatus.QUEUED
    )
    geometry_snapshot = models.JSONField(
        _("geometry snapshot"), default=dict, help_text=_("GeoJSON of the boundary analysed.")
    )
    started_at = models.DateTimeField(_("started at"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished at"), null=True, blank=True)

    class Meta:
        verbose_name = _("analysis run")
        verbose_name_plural = _("analysis runs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.parcel} · {self.created_at:%Y-%m-%d %H:%M}"


class ModuleResult(TimeStampedModel):
    """One record per analysis module per run, so a failed module never blocks the others."""

    run = models.ForeignKey(
        AnalysisRun, verbose_name=_("run"), on_delete=models.CASCADE, related_name="module_results"
    )
    module = models.CharField(_("module"), max_length=50)
    status = models.CharField(
        _("status"), max_length=16, choices=ModuleStatus.choices, default=ModuleStatus.PENDING
    )
    parameters = models.JSONField(_("parameters"), default=dict, blank=True)
    dataset_versions = models.JSONField(_("dataset versions"), default=dict, blank=True)
    results = models.JSONField(_("results"), default=dict, blank=True)
    layers = models.JSONField(_("map layers"), default=list, blank=True)
    maps = models.JSONField(
        _("static maps"),
        default=dict,
        blank=True,
        help_text=_("Storage key of the map per language."),
    )
    charts = models.JSONField(_("charts"), default=dict, blank=True)
    rating = models.CharField(
        _("rating"), max_length=8, choices=Rating.choices, default=Rating.GREY
    )
    error = models.TextField(_("error"), blank=True)
    ran_at = models.DateTimeField(_("ran at"), null=True, blank=True)

    class Meta:
        verbose_name = _("module result")
        verbose_name_plural = _("module results")
        constraints = [
            models.UniqueConstraint(fields=["run", "module"], name="unique_module_per_run")
        ]

    def __str__(self):
        return f"{self.module} ({self.status})"


class FindingTemplate(TimeStampedModel):
    """Plain-language finding per module and rating (FR-58, FR-49). Placeholders in braces,
    e.g. {area}, are filled from the module's results; numbers are formatted per language.
    Findings are never written by an LLM."""

    module = models.CharField(_("module"), max_length=50)
    rating = models.CharField(_("rating"), max_length=8, choices=Rating.choices)
    text = models.TextField(_("text"))  # translated: text_fr / text_en (see translation.py)

    class Meta:
        verbose_name = _("finding template")
        verbose_name_plural = _("finding templates")
        ordering = ["module", "rating"]
        constraints = [
            models.UniqueConstraint(fields=["module", "rating"], name="unique_template_per_rating")
        ]

    def __str__(self):
        return f"{self.module} / {self.rating}"


class PopulationStat(TimeStampedModel):
    """Cached zonal statistics: age-sex totals for one geometry, release and year (FR-56)."""

    key = models.CharField(max_length=120, unique=True)  # dataset:release:year:geometry hash
    release = models.CharField(_("release"), max_length=20)
    year = models.PositiveSmallIntegerField(_("year"))
    values = models.JSONField(_("values"))

    class Meta:
        verbose_name = _("population statistic")
        verbose_name_plural = _("population statistics")

    def __str__(self):
        return self.key
