from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class PageSlug(models.TextChoices):
    ABOUT = "about", _("About")
    TERMS = "terms", _("Terms of service")
    PRIVACY = "privacy", _("Privacy policy")
    DISCLAIMER = "disclaimer", _("Report disclaimer")


class Page(TimeStampedModel):
    """Admin-editable bilingual content page (FR-49). Title and body are translated."""

    slug = models.SlugField(_("page"), max_length=20, choices=PageSlug.choices, unique=True)
    title = models.CharField(_("title"), max_length=200)
    body = models.TextField(_("body"), help_text=_("Plain text. Blank lines separate paragraphs."))
    version = models.CharField(
        _("version"),
        max_length=20,
        blank=True,
        help_text=_("Shown on the page and recorded when customers accept the terms."),
    )
    is_draft = models.BooleanField(
        _("pending legal review"),
        default=True,
        help_text=_("Shows a notice that the text is a draft awaiting legal review."),
    )

    class Meta:
        verbose_name = _("page")
        verbose_name_plural = _("pages")
        ordering = ["slug"]

    def __str__(self):
        return self.get_slug_display()


class FAQItem(TimeStampedModel):
    question = models.CharField(_("question"), max_length=300)
    answer = models.TextField(_("answer"))
    sort_order = models.PositiveSmallIntegerField(_("sort order"), default=0)
    is_published = models.BooleanField(_("published"), default=True)

    class Meta:
        verbose_name = _("FAQ item")
        verbose_name_plural = _("FAQ")
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.question


class SampleReport(TimeStampedModel):
    title = models.CharField(_("title"), max_length=200)
    summary = models.TextField(_("summary"), blank=True)
    pdf_fr = models.FileField(_("PDF (French)"), upload_to="samples/", blank=True)
    pdf_en = models.FileField(_("PDF (English)"), upload_to="samples/", blank=True)
    sort_order = models.PositiveSmallIntegerField(_("sort order"), default=0)
    is_published = models.BooleanField(_("published"), default=False)

    class Meta:
        verbose_name = _("sample report")
        verbose_name_plural = _("sample reports")
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title

    def pdf_for(self, language):
        """The PDF in `language`, falling back to the other language."""
        preferred = self.pdf_en if language == "en" else self.pdf_fr
        return preferred or self.pdf_fr or self.pdf_en


class Lead(TimeStampedModel):
    """A contact request from the public site (FR-4)."""

    name = models.CharField(_("name"), max_length=200)
    email = models.EmailField(_("email"))
    phone = models.CharField(_("phone or WhatsApp"), max_length=32, blank=True)
    message = models.TextField(_("message"))
    language = models.CharField(_("language"), max_length=5, choices=settings.LANGUAGES)
    source_path = models.CharField(_("page"), max_length=300, blank=True)
    handled = models.BooleanField(_("handled"), default=False)
    notes = models.TextField(_("internal notes"), blank=True)

    class Meta:
        verbose_name = _("lead")
        verbose_name_plural = _("leads")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"
