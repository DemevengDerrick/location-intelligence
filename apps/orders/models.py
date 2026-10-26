import uuid

from django.conf import settings
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Currency, Organization
from apps.core.models import TimeStampedModel
from apps.parcels.choices import InputMethod


class OrderStatus(models.TextChoices):
    """Customer-visible order states (FR-18)."""

    SUBMITTED = "submitted", _("Submitted")
    PAID = "paid", _("Paid")
    NEEDS_GEOREFERENCING = "needs_georeferencing", _("Needs georeferencing")
    PROCESSING = "processing", _("Processing")
    IN_REVIEW = "in_review", _("In review")
    DELIVERED = "delivered", _("Delivered")
    FIELD_VISIT_SCHEDULED = "field_visit_scheduled", _("Field visit scheduled")
    FIELD_REPORT_DELIVERED = "field_report_delivered", _("Field report delivered")
    REFUNDED = "refunded", _("Refunded")


class IntendedUse(models.TextChoices):
    HOME = "home", _("Build a home")
    AGRICULTURE = "agriculture", _("Farming")
    COMMERCIAL = "commercial", _("Commercial project")
    INVESTMENT = "investment", _("Investment / resale")
    OTHER = "other", _("Other")


class Tier(models.TextChoices):
    DESK = "desk", _("Desk report")
    FIELD = "field", _("Desk report + field verification")


class Order(TimeStampedModel):
    public_id = models.UUIDField(_("public id"), default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("customer"),
        on_delete=models.PROTECT,
        related_name="orders",
    )
    organization = models.ForeignKey(
        Organization,
        verbose_name=_("organization"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    status = models.CharField(
        _("status"),
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.SUBMITTED,
        db_index=True,
    )
    tier = models.CharField(_("tier"), max_length=16, choices=Tier.choices, default=Tier.DESK)
    add_ons = models.JSONField(_("add-ons"), default=list, blank=True)
    currency = models.CharField(
        _("currency"), max_length=3, choices=Currency.choices, default=Currency.XAF
    )
    price_amount = models.DecimalField(
        _("price"), max_digits=12, decimal_places=2, null=True, blank=True
    )
    discount_amount = models.DecimalField(_("discount"), max_digits=12, decimal_places=2, default=0)
    language = models.CharField(
        _("report language"), max_length=5, choices=settings.LANGUAGES, default="fr"
    )
    intended_use = models.CharField(_("intended use"), max_length=200, blank=True)
    deadline = models.DateField(_("deadline"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    terms_version = models.CharField(_("terms version accepted"), max_length=20, blank=True)
    terms_accepted_at = models.DateTimeField(_("terms accepted at"), null=True, blank=True)
    paid_at = models.DateTimeField(_("paid at"), null=True, blank=True)
    delivered_at = models.DateTimeField(_("delivered at"), null=True, blank=True)

    class Meta:
        verbose_name = _("order")
        verbose_name_plural = _("orders")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.public_id)[:8]


class AttachmentKind(models.TextChoices):
    SITE_PLAN = "site_plan", _("Site plan")
    COORDINATES = "coordinates", _("Coordinates file")
    PHOTO = "photo", _("Photo")
    DOCUMENT = "document", _("Document")


class Attachment(TimeStampedModel):
    """A customer file. Uploaded against an intake draft, then moved to the order on submit."""

    order = models.ForeignKey(
        Order,
        verbose_name=_("order"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    draft = models.ForeignKey(
        "IntakeDraft",
        verbose_name=_("intake draft"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    kind = models.CharField(_("kind"), max_length=16, choices=AttachmentKind.choices)
    file = models.FileField(_("file"), upload_to="orders/attachments/%Y/%m/")
    original_name = models.CharField(_("original file name"), max_length=255, blank=True)
    content_type = models.CharField(_("content type"), max_length=100, blank=True)
    size_bytes = models.PositiveBigIntegerField(_("size (bytes)"), default=0)
    exif_location = models.PointField(_("EXIF location"), srid=4326, null=True, blank=True)
    exif_taken_at = models.DateTimeField(_("EXIF time"), null=True, blank=True)
    # Site plans: the analyst's control points and the fitted corners (FR-39).
    georeference = models.JSONField(_("georeference"), null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("uploaded by"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(order__isnull=False) | models.Q(draft__isnull=False),
                name="attachment_belongs_to_order_or_draft",
            )
        ]

    def __str__(self):
        return self.original_name or self.file.name


class Message(TimeStampedModel):
    order = models.ForeignKey(
        Order, verbose_name=_("order"), on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("author"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    body = models.TextField(_("message"))
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.order} · {self.created_at:%Y-%m-%d}"


class IntakeDraft(TimeStampedModel):
    """Order-form progress, saved after every step so a dropped connection can resume (NFR-4).

    Anonymous drafts are tied to the browser session; the token is also kept in the
    browser's localStorage so the customer can reclaim the draft if the session is lost.
    """

    STEPS = 5
    EXPIRY_DAYS = 30

    token = models.UUIDField(_("token"), default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("user"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="intake_drafts",
    )
    session_key = models.CharField(_("session"), max_length=40, blank=True, db_index=True)
    step_reached = models.PositiveSmallIntegerField(_("furthest step"), default=1)

    # Step 1: location
    input_method = models.CharField(
        _("input method"), max_length=16, choices=InputMethod.choices, blank=True
    )
    geometry = models.MultiPolygonField(_("boundary"), srid=4326, null=True, blank=True)
    pin = models.PointField(_("pin"), srid=4326, null=True, blank=True)
    computed_area_m2 = models.FloatField(_("computed area (m²)"), null=True, blank=True)
    is_approximate = models.BooleanField(_("approximate location"), default=False)
    location_warnings = models.JSONField(_("location warnings"), default=list, blank=True)

    # Step 2: details
    stated_area_m2 = models.FloatField(_("seller-stated area (m²)"), null=True, blank=True)
    quartier = models.CharField(_("quartier"), max_length=200, blank=True)
    commune = models.CharField(_("commune"), max_length=200, blank=True)
    region = models.CharField(_("region"), max_length=100, blank=True)
    title_number = models.CharField(_("land title number"), max_length=100, blank=True)
    intended_use = models.CharField(
        _("intended use"), max_length=20, choices=IntendedUse.choices, blank=True
    )
    notes = models.TextField(_("notes"), blank=True)

    # Step 3: tier
    tier = models.CharField(_("tier"), max_length=16, choices=Tier.choices, default=Tier.DESK)
    add_ons = models.JSONField(_("add-ons"), default=list, blank=True)
    deadline = models.DateField(_("deadline"), null=True, blank=True)
    report_language = models.CharField(
        _("report language"), max_length=5, choices=settings.LANGUAGES, default="fr"
    )
    currency = models.CharField(
        _("currency"), max_length=3, choices=Currency.choices, default=Currency.XAF
    )

    # Step 4: contact and terms
    contact_name = models.CharField(_("full name"), max_length=200, blank=True)
    contact_phone = models.CharField(_("phone or WhatsApp"), max_length=32, blank=True)
    terms_version = models.CharField(_("terms version accepted"), max_length=20, blank=True)
    terms_accepted_at = models.DateTimeField(_("terms accepted at"), null=True, blank=True)

    order = models.OneToOneField(
        Order,
        verbose_name=_("order"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intake_draft",
    )

    class Meta:
        verbose_name = _("intake draft")
        verbose_name_plural = _("intake drafts")
        ordering = ["-updated_at"]

    def __str__(self):
        return str(self.token)[:8]

    @property
    def is_submitted(self):
        return self.order_id is not None

    @property
    def has_location(self):
        return self.geometry is not None or (
            self.input_method == InputMethod.SITE_PLAN
            and self.attachments.filter(kind=AttachmentKind.SITE_PLAN).exists()
        )
