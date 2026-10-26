import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Currency
from apps.core.models import TimeStampedModel
from apps.orders.models import Order


class PaymentProviderName(models.TextChoices):
    STRIPE = "stripe", "Stripe"
    MOBILE_MONEY = "mobile_money", _("Mobile money aggregator")
    MANUAL = "manual", _("Manual (bank transfer)")
    FAKE = "fake", _("Demo (fake)")


class PaymentMethod(models.TextChoices):
    CARD = "card", _("Card")
    MOBILE_MONEY = "mobile_money", _("Mobile money")
    BANK_TRANSFER = "bank_transfer", _("Bank transfer")
    FREE = "free", _("Free (full discount)")


class PaymentPurpose(models.TextChoices):
    ORDER = "order", _("Order")
    UPGRADE = "upgrade", _("Upgrade to field verification")


class PaymentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCEEDED = "succeeded", _("Succeeded")
    FAILED = "failed", _("Failed")
    REFUNDED = "refunded", _("Refunded")


class Payment(TimeStampedModel):
    public_id = models.UUIDField(_("public id"), default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey(
        Order, verbose_name=_("order"), on_delete=models.PROTECT, related_name="payments"
    )
    provider = models.CharField(_("provider"), max_length=16, choices=PaymentProviderName.choices)
    method = models.CharField(
        _("method"), max_length=16, choices=PaymentMethod.choices, default=PaymentMethod.CARD
    )
    purpose = models.CharField(
        _("purpose"), max_length=8, choices=PaymentPurpose.choices, default=PaymentPurpose.ORDER
    )
    provider_reference = models.CharField(_("provider reference"), max_length=200)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    currency = models.CharField(_("currency"), max_length=3, choices=Currency.choices)
    discount_code = models.ForeignKey(
        "DiscountCode",
        verbose_name=_("discount code"),
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    discount_amount = models.DecimalField(_("discount"), max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        _("status"), max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    succeeded_at = models.DateTimeField(_("succeeded at"), null=True, blank=True)
    raw_webhook = models.JSONField(_("raw webhook"), default=dict, blank=True)
    refunded_amount = models.DecimalField(
        _("refunded amount"), max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["-created_at"]
        constraints = [
            # Webhook idempotency (FR-14): one row per provider transaction.
            models.UniqueConstraint(
                fields=["provider", "provider_reference"], name="unique_provider_reference"
            )
        ]

    def __str__(self):
        return f"{self.provider}:{self.provider_reference}"

    @property
    def refundable_amount(self):
        return self.amount - self.refunded_amount


class Refund(TimeStampedModel):
    """A refund triggered from the admin and recorded against the payment (FR-16)."""

    payment = models.ForeignKey(
        Payment, verbose_name=_("payment"), on_delete=models.PROTECT, related_name="refunds"
    )
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)
    reason = models.TextField(_("reason"))
    provider_reference = models.CharField(_("provider reference"), max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("refund")
        verbose_name_plural = _("refunds")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.amount} {self.payment.currency} ({self.payment})"


class WebhookEvent(models.Model):
    """Every provider event received, so a replayed webhook is processed once (FR-14)."""

    provider = models.CharField(_("provider"), max_length=16, choices=PaymentProviderName.choices)
    event_id = models.CharField(_("event id"), max_length=200)
    event_type = models.CharField(_("event type"), max_length=100, blank=True)
    payload = models.JSONField(_("payload"), default=dict)
    received_at = models.DateTimeField(_("received at"), auto_now_add=True)
    processed_at = models.DateTimeField(_("processed at"), null=True, blank=True)
    outcome = models.CharField(_("outcome"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("webhook event")
        verbose_name_plural = _("webhook events")
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="unique_webhook_event")
        ]

    def __str__(self):
        return f"{self.provider}:{self.event_id}"


class DiscountKind(models.TextChoices):
    PERCENT = "percent", _("Percentage")
    FIXED = "fixed", _("Fixed amount")


class DiscountCode(TimeStampedModel):
    code = models.CharField(_("code"), max_length=40, unique=True)
    kind = models.CharField(_("kind"), max_length=8, choices=DiscountKind.choices)
    value = models.DecimalField(_("value"), max_digits=12, decimal_places=2)
    currency = models.CharField(
        _("currency"),
        max_length=3,
        choices=Currency.choices,
        blank=True,
        help_text=_("Required for fixed-amount codes."),
    )
    expires_at = models.DateTimeField(_("expires at"), null=True, blank=True)
    usage_limit = models.PositiveIntegerField(_("usage limit"), null=True, blank=True)
    times_used = models.PositiveIntegerField(_("times used"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("discount code")
        verbose_name_plural = _("discount codes")

    def __str__(self):
        return self.code

    def clean(self):
        self.code = self.code.strip().upper()
        if self.kind == DiscountKind.FIXED and not self.currency:
            raise ValidationError({"currency": _("Required for fixed-amount codes.")})
        if self.kind == DiscountKind.PERCENT and not 0 < self.value <= 100:
            raise ValidationError({"value": _("A percentage must be between 0 and 100.")})

    @property
    def is_usable(self):
        return (
            self.is_active
            and (self.expires_at is None or self.expires_at > timezone.now())
            and (self.usage_limit is None or self.times_used < self.usage_limit)
        )
