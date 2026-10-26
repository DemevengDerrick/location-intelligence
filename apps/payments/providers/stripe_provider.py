"""Card payments through Stripe Checkout (FR-12)."""

import json

import stripe
from django.conf import settings

from .base import (
    CheckoutSession,
    InvalidSignature,
    PaymentProvider,
    WebhookResult,
    from_minor,
    to_minor,
)

SUCCEEDED_EVENTS = {"checkout.session.completed", "checkout.session.async_payment_succeeded"}
FAILED_EVENTS = {"checkout.session.async_payment_failed", "checkout.session.expired"}


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self, secret_key=None, webhook_secret=None):
        self.client = stripe.StripeClient(secret_key or settings.STRIPE_SECRET_KEY)
        self.webhook_secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET

    def create_checkout(
        self, payment, *, success_url, cancel_url, customer_email, language, description
    ):
        metadata = {"payment": str(payment.public_id), "order": str(payment.order.public_id)}
        session = self.client.v1.checkout.sessions.create(
            params={
                "mode": "payment",
                "line_items": [
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": payment.currency.lower(),
                            "unit_amount": to_minor(payment.amount, payment.currency),
                            "product_data": {"name": description},
                        },
                    }
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": customer_email,
                "client_reference_id": str(payment.public_id),
                "locale": language if language in ("fr", "en") else "auto",
                "metadata": metadata,
                "payment_intent_data": {"metadata": metadata},
            }
        )
        return CheckoutSession(provider_reference=session.id, redirect_url=session.url)

    def parse_webhook(self, body, headers):
        try:
            stripe.Webhook.construct_event(
                body, headers.get("Stripe-Signature", ""), self.webhook_secret
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise InvalidSignature(str(exc)) from exc

        event = json.loads(body)
        session = event["data"]["object"]
        outcome = "ignored"
        if event["type"] in SUCCEEDED_EVENTS and session.get("payment_status") == "paid":
            outcome = "succeeded"
        elif event["type"] in FAILED_EVENTS:
            outcome = "failed"
        currency = (session.get("currency") or "").upper()
        amount = session.get("amount_total")
        return WebhookResult(
            event_id=event["id"],
            event_type=event["type"],
            provider_reference=session.get("id", ""),
            outcome=outcome,
            amount=from_minor(amount, currency) if amount is not None and currency else None,
            currency=currency,
            payload=event,
        )

    def refund(self, payment, amount):
        payment_intent = payment.raw_webhook.get("data", {}).get("object", {}).get("payment_intent")
        if not payment_intent:
            raise ValueError("No Stripe payment intent recorded for this payment")
        refund = self.client.v1.refunds.create(
            params={
                "payment_intent": payment_intent,
                "amount": to_minor(amount, payment.currency),
            }
        )
        return refund.id
