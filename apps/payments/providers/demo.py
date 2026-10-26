"""Demo provider for development and sales demos (NFR-18), and the stand-in for mobile money
until an aggregator is chosen. It never moves money, but it goes through the same path as a
real provider: hosted checkout page → signed webhook → verification → order paid."""

import hashlib
import hmac
import json
import uuid
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from .base import CheckoutSession, InvalidSignature, PaymentProvider, WebhookResult

SIGNATURE_HEADER = "X-Demo-Signature"


def _sign(body: bytes) -> str:
    return hmac.new(settings.DEMO_PAYMENT_SECRET.encode(), body, hashlib.sha256).hexdigest()


class DemoProvider(PaymentProvider):
    name = "fake"

    def create_checkout(
        self, payment, *, success_url, cancel_url, customer_email, language, description
    ):
        return CheckoutSession(
            provider_reference=f"demo_{uuid.uuid4().hex}",
            redirect_url=reverse("payments:demo", args=[payment.public_id]),
        )

    def build_event(self, payment, outcome):
        """The signed webhook the demo checkout page delivers after approve/decline."""
        body = json.dumps(
            {
                "id": f"evt_demo_{uuid.uuid4().hex}",
                "type": f"payment.{outcome}",
                "reference": payment.provider_reference,
                "outcome": outcome,
                "amount": str(payment.amount),
                "currency": payment.currency,
            }
        ).encode()
        return body, {SIGNATURE_HEADER: _sign(body)}

    def parse_webhook(self, body, headers):
        if not hmac.compare_digest(headers.get(SIGNATURE_HEADER, ""), _sign(body)):
            raise InvalidSignature("bad demo signature")
        event = json.loads(body)
        return WebhookResult(
            event_id=event["id"],
            event_type=event["type"],
            provider_reference=event["reference"],
            outcome=event["outcome"],
            amount=Decimal(event["amount"]),
            currency=event["currency"],
            payload=event,
        )

    def refund(self, payment, amount):
        return f"demo_refund_{uuid.uuid4().hex}"


class ManualProvider(PaymentProvider):
    """Bank transfers marked as paid by an admin, and free (100% discount) orders.
    Refunds are paid outside the platform and only recorded here."""

    name = "manual"

    def create_checkout(self, *args, **kwargs):
        raise NotImplementedError("Manual payments have no checkout")

    def parse_webhook(self, body, headers):
        raise InvalidSignature("Manual payments have no webhooks")

    def refund(self, payment, amount):
        return ""
