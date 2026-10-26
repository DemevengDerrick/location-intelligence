"""Payment business logic. Orders become "paid" only here, and only from a verified provider
event or an admin action, never from a browser redirect (FR-14)."""

import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.analysis.tasks import start_analysis
from apps.core.audit import log_action
from apps.orders.models import Order, OrderStatus, Tier
from apps.orders.status import transition
from apps.pricing.models import ProductPrice

from .models import (
    DiscountCode,
    DiscountKind,
    Payment,
    PaymentMethod,
    PaymentProviderName,
    PaymentPurpose,
    PaymentStatus,
    Refund,
)
from .providers import checkout_provider, provider_named
from .tasks import send_receipt

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """A problem to show the customer or the admin."""


# --- Quotes and discounts ----------------------------------------------------------------


@dataclass(frozen=True)
class Quote:
    subtotal: Decimal
    discount: Decimal
    currency: str

    @property
    def total(self):
        return max(self.subtotal - self.discount, Decimal("0"))


def payment_currency(order, method):
    """Mobile money is always paid in XAF; other methods in the order's currency."""
    return "XAF" if method == PaymentMethod.MOBILE_MONEY else order.currency


def _list_price(order, currency):
    if currency == order.currency:
        return order.price_amount
    codes = [order.tier, *order.add_ons]
    prices = dict(
        ProductPrice.objects.filter(product__code__in=codes, currency=currency).values_list(
            "product__code", "amount"
        )
    )
    if any(code not in prices for code in codes):
        return None
    return sum((prices[c] for c in codes), Decimal("0"))


def find_discount(text):
    """The usable code matching `text`, or raise PaymentError with a customer message."""
    code = DiscountCode.objects.filter(code__iexact=(text or "").strip()).first()
    if code is None or not code.is_usable:
        raise PaymentError(_("This discount code is not valid or has expired."))
    return code


def discount_for(code, subtotal, currency):
    if code is None:
        return Decimal("0")
    if code.kind == DiscountKind.PERCENT:
        decimals = Decimal("1") if currency == "XAF" else Decimal("0.01")
        return (subtotal * code.value / 100).quantize(decimals, rounding=ROUND_HALF_UP)
    if code.currency != currency:
        raise PaymentError(
            _("This code only applies to payments in %(currency)s.") % {"currency": code.currency}
        )
    return min(code.value, subtotal)


def quote(order, method, code=None):
    currency = payment_currency(order, method)
    subtotal = _list_price(order, currency)
    if subtotal is None:
        raise PaymentError(_("This report has no price in %(currency)s.") % {"currency": currency})
    return Quote(subtotal, discount_for(code, subtotal, currency), currency)


# --- Field-verification upgrade (FR-20, Journey C) ---------------------------------------

UPGRADABLE_STATUSES = {
    OrderStatus.PAID,
    OrderStatus.NEEDS_GEOREFERENCING,
    OrderStatus.PROCESSING,
    OrderStatus.IN_REVIEW,
    OrderStatus.DELIVERED,
}


def can_upgrade(order):
    return (
        order.tier == Tier.DESK
        and order.status in UPGRADABLE_STATUSES
        and not order.payments.filter(
            purpose=PaymentPurpose.UPGRADE, status=PaymentStatus.SUCCEEDED
        ).exists()
    )


def upgrade_quote(order, method):
    """The difference between the field and desk tiers, in the payment currency."""
    currency = payment_currency(order, method)
    prices = dict(
        ProductPrice.objects.filter(
            product__code__in=[Tier.DESK, Tier.FIELD], currency=currency
        ).values_list("product__code", "amount")
    )
    if Tier.DESK not in prices or Tier.FIELD not in prices:
        raise PaymentError(_("This report has no price in %(currency)s.") % {"currency": currency})
    return Quote(prices[Tier.FIELD] - prices[Tier.DESK], Decimal("0"), currency)


# --- Starting a payment ------------------------------------------------------------------


def start_payment(order, method, code, request, purpose=PaymentPurpose.ORDER):
    """Create a pending Payment and return the URL to send the customer to."""
    if purpose == PaymentPurpose.UPGRADE:
        if not can_upgrade(order):
            raise PaymentError(_("This order cannot be upgraded."))
        code = None
        q = upgrade_quote(order, method)
    else:
        if order.status != OrderStatus.SUBMITTED:
            raise PaymentError(_("This order has already been paid."))
        if code is not None and not code.is_usable:
            raise PaymentError(_("This discount code is not valid or has expired."))
        q = quote(order, method, code)

    if q.total == 0:
        payment = Payment.objects.create(
            order=order,
            provider=PaymentProviderName.MANUAL,
            method=PaymentMethod.FREE,
            provider_reference=f"free_{uuid.uuid4().hex}",
            amount=Decimal("0"),
            currency=q.currency,
            discount_code=code,
            discount_amount=q.discount,
        )
        mark_succeeded(
            payment, amount=Decimal("0"), currency=q.currency, payload={}, request=request
        )
        return reverse("payments:return", args=[payment.public_id])

    provider = checkout_provider(method)
    if provider is None:
        raise PaymentError(_("This payment method is not available yet."))
    payment = Payment.objects.create(
        order=order,
        provider=provider.name,
        method=method,
        purpose=purpose,
        provider_reference=f"pending_{uuid.uuid4().hex}",
        amount=q.total,
        currency=q.currency,
        discount_code=code,
        discount_amount=q.discount,
    )
    return_url = request.build_absolute_uri(reverse("payments:return", args=[payment.public_id]))
    back = "portal:order" if purpose == PaymentPurpose.UPGRADE else "payments:pay"
    cancel_url = request.build_absolute_uri(reverse(back, args=[order.public_id]))
    description = (
        _("Field verification for land report %(ref)s")
        if purpose == PaymentPurpose.UPGRADE
        else _("Land report %(ref)s")
    ) % {"ref": str(order.public_id)[:8]}
    try:
        session = provider.create_checkout(
            payment,
            success_url=return_url,
            cancel_url=cancel_url,
            customer_email=order.customer.email,
            language=order.language,
            description=description,
        )
    except Exception as exc:
        logger.exception("Checkout creation failed for payment %s", payment.public_id)
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise PaymentError(_("The payment could not be started. Please try again.")) from exc
    payment.provider_reference = session.provider_reference
    payment.save(update_fields=["provider_reference", "updated_at"])
    log_action("payment.started", actor=request.user, target=payment, request=request)
    return session.redirect_url


# --- Outcomes ----------------------------------------------------------------------------


@transaction.atomic
def mark_succeeded(payment, *, amount, currency, payload, actor=None, request=None):
    """Record a successful payment and move the order on. Idempotent. Returns an outcome."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == PaymentStatus.SUCCEEDED:
        return "already succeeded"
    if amount is not None and (amount != payment.amount or currency != payment.currency):
        logger.error(
            "Amount mismatch on %s: expected %s %s, got %s %s",
            payment,
            payment.amount,
            payment.currency,
            amount,
            currency,
        )
        payment.raw_webhook = payload
        payment.save(update_fields=["raw_webhook", "updated_at"])
        log_action("payment.amount_mismatch", actor=actor, target=payment, request=request)
        return "amount mismatch"

    payment.status = PaymentStatus.SUCCEEDED
    payment.succeeded_at = timezone.now()
    payment.raw_webhook = payload
    payment.save(update_fields=["status", "succeeded_at", "raw_webhook", "updated_at"])
    if payment.discount_code_id:
        DiscountCode.objects.filter(pk=payment.discount_code_id).update(
            times_used=F("times_used") + 1
        )
    log_action("payment.succeeded", actor=actor, target=payment, request=request)

    order = Order.objects.select_for_update().get(pk=payment.order_id)
    if payment.purpose == PaymentPurpose.UPGRADE:
        return _apply_upgrade(order, payment, actor=actor, request=request)
    if order.status != OrderStatus.SUBMITTED:
        # Paid twice (e.g. two tabs). Keep the money on record; an admin refunds the extra.
        log_action("payment.duplicate", actor=actor, target=payment, request=request)
        return "duplicate payment"
    order.discount_amount = payment.discount_amount
    order.save(update_fields=["discount_amount", "updated_at"])
    transition(order, OrderStatus.PAID, actor=actor, request=request)
    needs_geometry = order.parcels.filter(geometry__isnull=True).exists()
    if needs_geometry:
        transition(order, OrderStatus.NEEDS_GEOREFERENCING, actor=actor, request=request)
    else:
        transition(order, OrderStatus.PROCESSING, actor=actor, request=request)
        transaction.on_commit(lambda: start_analysis.delay(order.pk))
    transaction.on_commit(lambda: send_receipt.delay(payment.pk))
    return "paid"


def _apply_upgrade(order, payment, *, actor, request):
    order.tier = Tier.FIELD
    fields = ["tier", "updated_at"]
    if payment.currency == order.currency:
        order.price_amount += payment.amount
        fields.append("price_amount")
    order.save(update_fields=fields)
    log_action("order.upgraded", actor=actor, target=order, request=request)
    transaction.on_commit(lambda: send_receipt.delay(payment.pk))
    return "upgraded"


def mark_failed(payment, payload):
    updated = Payment.objects.filter(pk=payment.pk, status=PaymentStatus.PENDING).update(
        status=PaymentStatus.FAILED, raw_webhook=payload, updated_at=timezone.now()
    )
    return "failed" if updated else "ignored"


def mark_paid_manually(order, *, reference, actor, request=None):
    """Admin-only "mark as paid" for bank transfers (FR-15)."""
    payment = Payment.objects.create(
        order=order,
        provider=PaymentProviderName.MANUAL,
        method=PaymentMethod.BANK_TRANSFER,
        provider_reference=reference or f"bank_{uuid.uuid4().hex}",
        amount=order.price_amount,
        currency=order.currency,
    )
    return mark_succeeded(
        payment,
        amount=None,
        currency=None,
        payload={"reference": reference},
        actor=actor,
        request=request,
    )


@transaction.atomic
def refund(payment, *, amount, reason, actor, request=None):
    """Refund through the provider and record it on the payment and order (FR-16)."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED):
        raise PaymentError(_("Only successful payments can be refunded."))
    if not Decimal("0") < amount <= payment.refundable_amount:
        raise PaymentError(
            _("The amount must be between 0 and %(max)s.") % {"max": payment.refundable_amount}
        )
    reference = provider_named(payment.provider).refund(payment, amount)
    Refund.objects.create(
        payment=payment,
        amount=amount,
        reason=reason,
        provider_reference=reference,
        created_by=actor,
    )
    payment.refunded_amount += amount
    if payment.refundable_amount == 0:
        payment.status = PaymentStatus.REFUNDED
    payment.save(update_fields=["refunded_amount", "status", "updated_at"])
    log_action(
        "payment.refunded",
        actor=actor,
        target=payment,
        request=request,
        data={"amount": str(amount), "reason": reason},
    )

    order = Order.objects.select_for_update().get(pk=payment.order_id)
    still_paid = order.payments.filter(status=PaymentStatus.SUCCEEDED).exists()
    if payment.status == PaymentStatus.REFUNDED and not still_paid:
        if order.status != OrderStatus.REFUNDED:
            transition(order, OrderStatus.REFUNDED, actor=actor, request=request, note=reason)
    return payment
