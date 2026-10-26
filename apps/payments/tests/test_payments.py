import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone, translation

from apps.accounts import roles
from apps.core.models import AuditLog
from apps.orders.models import OrderStatus
from apps.orders.status import InvalidTransition, transition
from apps.orders.testing import make_order
from apps.payments import services
from apps.payments.models import (
    DiscountCode,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Refund,
    WebhookEvent,
)
from apps.payments.providers.demo import DemoProvider
from apps.payments.providers.stripe_provider import StripeProvider

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


@pytest.fixture
def order(customer):
    return make_order(customer)


@pytest.fixture
def signed_in(client, customer):
    client.force_login(customer)
    return client


def pay(client, order, method="card", **extra):
    return client.post(reverse("payments:pay", args=[order.public_id]), {"method": method, **extra})


def approve(client, payment, decision="approve"):
    return client.post(reverse("payments:demo", args=[payment.public_id]), {"decision": decision})


# --- Demo checkout: the full path ---------------------------------------------------------


def test_pay_page_offers_card_and_mobile_money(signed_in, order):
    html = signed_in.get(reverse("payments:pay", args=[order.public_id])).content.decode()
    assert "Card" in html and "Mobile money" in html
    assert "FCFA" in html and "10,000" in html
    assert "Demo mode" in html


def test_card_payment_marks_order_paid_only_via_webhook(
    signed_in, order, customer, django_capture_on_commit_callbacks
):
    customer.language = "fr"
    customer.save()
    response = pay(signed_in, order)
    payment = Payment.objects.get()
    assert response.url == reverse("payments:demo", args=[payment.public_id])
    assert payment.status == PaymentStatus.PENDING

    # Landing on the return page must not mark anything as paid (FR-14).
    signed_in.get(reverse("payments:return", args=[payment.public_id]))
    order.refresh_from_db()
    assert order.status == OrderStatus.SUBMITTED

    with django_capture_on_commit_callbacks(execute=True):
        response = approve(signed_in, payment)
    assert response.url == reverse("payments:return", args=[payment.public_id])

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.amount == Decimal("10000")
    assert order.status == OrderStatus.PROCESSING
    assert order.paid_at is not None
    statuses = [e.data["to"] for e in AuditLog.objects.filter(action="order.status").order_by("pk")]
    assert statuses == ["paid", "processing"]

    receipt = mail.outbox[-1]
    assert receipt.to == [customer.email]
    assert "Reçu pour la commande" in receipt.subject  # customer's language, not the site's
    assert "10 000" in receipt.body.replace(" ", " ").replace("\xa0", " ")

    html = signed_in.get(reverse("payments:return", args=[payment.public_id])).content.decode()
    assert "Payment received" in html


def test_site_plan_order_waits_for_georeferencing(signed_in, customer):
    order = make_order(customer, geometry=False)
    pay(signed_in, order)
    approve(signed_in, Payment.objects.get())
    order.refresh_from_db()
    assert order.status == OrderStatus.NEEDS_GEOREFERENCING


def test_declined_payment_leaves_order_unpaid(signed_in, order):
    pay(signed_in, order)
    payment = Payment.objects.get()
    approve(signed_in, payment, decision="decline")

    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatus.FAILED
    assert order.status == OrderStatus.SUBMITTED
    html = signed_in.get(reverse("payments:return", args=[payment.public_id])).content.decode()
    assert "did not go through" in html


def test_mobile_money_is_charged_in_xaf_from_the_price_list(signed_in, customer):
    order = make_order(customer, currency="EUR", price="15")
    pay(signed_in, order, method="mobile_money")
    payment = Payment.objects.get()
    assert payment.method == PaymentMethod.MOBILE_MONEY
    assert (payment.amount, payment.currency) == (Decimal("10000"), "XAF")


def test_other_customers_cannot_reach_payment_pages(signed_in, order, make_user):
    pay(signed_in, order)
    payment = Payment.objects.get()
    intruder = Client()
    intruder.force_login(make_user("other@example.com", role=roles.CUSTOMER))
    assert intruder.get(reverse("payments:pay", args=[order.public_id])).status_code == 404
    assert intruder.get(reverse("payments:return", args=[payment.public_id])).status_code == 404
    assert approve(intruder, payment).status_code == 404


def test_paid_order_cannot_be_paid_again(signed_in, order):
    pay(signed_in, order)
    approve(signed_in, Payment.objects.get())
    response = pay(signed_in, order)
    assert Payment.objects.count() == 1
    assert "already paid" in signed_in.get(response.url).content.decode()


# --- Webhook security and idempotency ------------------------------------------------------


def test_replayed_webhook_is_processed_once(signed_in, order, client):
    pay(signed_in, order)
    payment = Payment.objects.get()
    body, headers = DemoProvider().build_event(payment, "succeeded")
    url = reverse("demo_webhook")
    kwargs = {
        "content_type": "application/json",
        "HTTP_X_DEMO_SIGNATURE": headers["X-Demo-Signature"],
    }

    first = Client().post(url, body, **kwargs)
    second = Client().post(url, body, **kwargs)
    assert first.content == b"paid"
    assert second.content == b"duplicate event"
    assert WebhookEvent.objects.count() == 1
    assert AuditLog.objects.filter(action="payment.succeeded").count() == 1


def test_webhook_with_bad_signature_changes_nothing(signed_in, order):
    pay(signed_in, order)
    payment = Payment.objects.get()
    body, _headers = DemoProvider().build_event(payment, "succeeded")
    response = Client().post(
        reverse("demo_webhook"),
        body,
        content_type="application/json",
        HTTP_X_DEMO_SIGNATURE="forged",
    )
    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == OrderStatus.SUBMITTED
    assert not WebhookEvent.objects.exists()


def test_amount_mismatch_does_not_mark_paid(signed_in, order):
    pay(signed_in, order)
    payment = Payment.objects.get()
    payment.amount = Decimal("1")  # what the event will claim
    body, headers = DemoProvider().build_event(payment, "succeeded")
    response = Client().post(
        reverse("demo_webhook"),
        body,
        content_type="application/json",
        HTTP_X_DEMO_SIGNATURE=headers["X-Demo-Signature"],
    )
    assert response.content == b"amount mismatch"
    order.refresh_from_db()
    assert order.status == OrderStatus.SUBMITTED


def test_demo_endpoints_are_off_outside_demo_mode(signed_in, order, settings):
    pay(signed_in, order)
    payment = Payment.objects.get()
    settings.PAYMENTS_DEMO_MODE = False
    assert approve(signed_in, payment).status_code == 404
    assert (
        Client().post(reverse("demo_webhook"), b"{}", content_type="application/json").status_code
        == 404
    )


# --- Stripe --------------------------------------------------------------------------------


def stripe_signature(body: bytes, secret="whsec_test_dummy"):
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.fixture
def stripe_live(settings, monkeypatch):
    """Card payments through Stripe (demo mode off), with the API calls captured."""
    settings.PAYMENTS_DEMO_MODE = False
    calls = {}

    def create_session(params):
        calls["session"] = params
        return SimpleNamespace(id="cs_test_123", url="https://checkout.stripe.test/cs_test_123")

    def create_refund(params):
        calls["refund"] = params
        return SimpleNamespace(id="re_test_1")

    class FakeStripeClient:
        def __init__(self, api_key):
            self.v1 = SimpleNamespace(
                checkout=SimpleNamespace(sessions=SimpleNamespace(create=create_session)),
                refunds=SimpleNamespace(create=create_refund),
            )

    monkeypatch.setattr(
        "apps.payments.providers.stripe_provider.stripe.StripeClient", FakeStripeClient
    )
    return calls


@pytest.mark.parametrize("currency, price, minor", [("XAF", "10000", 10000), ("EUR", "15", 1500)])
def test_stripe_checkout_uses_minor_units(signed_in, customer, stripe_live, currency, price, minor):
    order = make_order(customer, currency=currency, price=price)
    response = pay(signed_in, order)
    assert response.url == "https://checkout.stripe.test/cs_test_123"
    line = stripe_live["session"]["line_items"][0]["price_data"]
    assert (line["currency"], line["unit_amount"]) == (currency.lower(), minor)
    assert Payment.objects.get().provider_reference == "cs_test_123"


def test_only_card_is_offered_without_a_mobile_money_aggregator(signed_in, order, stripe_live):
    html = signed_in.get(reverse("payments:pay", args=[order.public_id])).content.decode()
    assert "Visa, Mastercard" in html
    assert "MTN Mobile Money" not in html


def stripe_event(event_type="checkout.session.completed", amount=10000, currency="xaf"):
    return json.dumps(
        {
            "id": "evt_test_1",
            "type": event_type,
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_status": "paid",
                    "amount_total": amount,
                    "currency": currency,
                    "payment_intent": "pi_test_1",
                }
            },
        }
    ).encode()


def test_stripe_webhook_marks_order_paid_and_refund_goes_to_stripe(
    signed_in, order, stripe_live, admin_user
):
    pay(signed_in, order)
    body = stripe_event()
    response = Client().post(
        reverse("stripe_webhook"),
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=stripe_signature(body),
    )
    assert response.content == b"paid"
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING

    payment = Payment.objects.get()
    services.refund(payment, amount=Decimal("4000"), reason="Partial goodwill", actor=admin_user)
    assert stripe_live["refund"] == {"payment_intent": "pi_test_1", "amount": 4000}
    assert Refund.objects.get().provider_reference == "re_test_1"


def test_stripe_webhook_rejects_bad_signatures(signed_in, order, stripe_live):
    pay(signed_in, order)
    body = stripe_event()
    response = Client().post(
        reverse("stripe_webhook"),
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=stripe_signature(body, secret="whsec_wrong"),
    )
    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == OrderStatus.SUBMITTED


def test_stripe_provider_ignores_unpaid_sessions():
    body = json.dumps(
        {
            "id": "evt_2",
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "payment_status": "unpaid"}},
        }
    ).encode()
    provider = StripeProvider(secret_key="sk_test", webhook_secret="whsec_test_dummy")
    result = provider.parse_webhook(body, {"Stripe-Signature": stripe_signature(body)})
    assert result.outcome == "ignored"


# --- Discount codes ------------------------------------------------------------------------


def code(**fields):
    defaults = {"code": "WELCOME", "kind": "percent", "value": Decimal("50")}
    return DiscountCode.objects.create(**(defaults | fields))


def test_percentage_code_halves_the_price_and_counts_only_on_success(signed_in, order):
    discount = code(usage_limit=1)
    signed_in.post(
        reverse("payments:pay", args=[order.public_id]), {"action": "apply_code", "code": "welcome"}
    )
    pay(signed_in, order)
    payment = Payment.objects.get()
    assert (payment.amount, payment.discount_amount) == (Decimal("5000"), Decimal("5000"))
    discount.refresh_from_db()
    assert discount.times_used == 0

    approve(signed_in, payment)
    discount.refresh_from_db()
    order.refresh_from_db()
    assert discount.times_used == 1
    assert order.discount_amount == Decimal("5000")
    assert not discount.is_usable  # limit reached


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"expires_at": timezone.now() - timedelta(days=1)}, "not valid or has expired"),
        ({"is_active": False}, "not valid or has expired"),
        ({"usage_limit": 2, "times_used": 2}, "not valid or has expired"),
    ],
)
def test_unusable_codes_are_refused(signed_in, order, fields, message):
    code(**fields)
    response = signed_in.post(
        reverse("payments:pay", args=[order.public_id]),
        {"action": "apply_code", "code": "WELCOME"},
        follow=True,
    )
    assert message in response.content.decode()


def test_fixed_code_only_applies_in_its_currency(order):
    discount = code(kind="fixed", value=Decimal("5"), currency="EUR")
    with pytest.raises(services.PaymentError, match="only applies to payments in EUR"):
        services.quote(order, PaymentMethod.CARD, discount)


def test_full_discount_completes_the_order_without_a_provider(signed_in, order):
    code(value=Decimal("100"))
    signed_in.post(
        reverse("payments:pay", args=[order.public_id]), {"action": "apply_code", "code": "WELCOME"}
    )
    response = pay(signed_in, order)
    payment = Payment.objects.get()
    assert payment.method == PaymentMethod.FREE
    assert response.url == reverse("payments:return", args=[payment.public_id])
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING


# --- Admin: mark as paid and refunds -------------------------------------------------------


def test_admin_marks_a_bank_transfer_as_paid(client, order, make_user):
    admin = make_user("founder@example.com", role=roles.ADMIN, is_staff=True)
    client.force_login(admin)
    url = reverse("admin:orders_order_changelist")
    data = {"action": "mark_paid", ACTION_CHECKBOX_NAME: [order.pk]}

    form = client.post(url, data)
    assert "Bank transfer reference" in form.content.decode()
    client.post(url, {**data, "apply": "1", "reference": "UBA-2026-1042"})

    order.refresh_from_db()
    payment = Payment.objects.get()
    assert order.status == OrderStatus.PROCESSING
    assert (payment.method, payment.provider_reference) == ("bank_transfer", "UBA-2026-1042")


def test_analysts_cannot_mark_orders_paid(client, order, analyst):
    analyst.is_staff = True
    analyst.save()
    client.force_login(analyst)
    client.post(
        reverse("admin:orders_order_changelist"),
        {"action": "mark_paid", ACTION_CHECKBOX_NAME: [order.pk], "apply": "1", "reference": "X"},
    )
    order.refresh_from_db()
    assert order.status == OrderStatus.SUBMITTED
    assert not Payment.objects.exists()


def test_full_refund_marks_order_refunded(signed_in, order, admin_user):
    pay(signed_in, order)
    payment = Payment.objects.get()
    approve(signed_in, payment)

    services.refund(payment, amount=Decimal("4000"), reason="Partial", actor=admin_user)
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING  # partial refund keeps the order going

    services.refund(payment, amount=Decimal("6000"), reason="Cancelled", actor=admin_user)
    payment.refresh_from_db()
    order.refresh_from_db()
    assert payment.status == PaymentStatus.REFUNDED
    assert payment.refunded_amount == Decimal("10000")
    assert order.status == OrderStatus.REFUNDED
    assert Refund.objects.count() == 2

    with pytest.raises(services.PaymentError):
        services.refund(payment, amount=Decimal("1"), reason="Too much", actor=admin_user)


def test_invalid_status_transitions_are_refused(order):
    with pytest.raises(InvalidTransition):
        transition(order, OrderStatus.DELIVERED)
