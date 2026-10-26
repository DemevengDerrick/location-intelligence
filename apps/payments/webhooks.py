"""Webhook processing shared by every provider: verify, de-duplicate, apply."""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Payment, WebhookEvent
from .providers import provider_named
from .services import mark_failed, mark_succeeded

logger = logging.getLogger(__name__)


def handle_webhook(provider_name, body: bytes, headers) -> str:
    """Raises InvalidSignature for unauthenticated events; returns the outcome otherwise."""
    result = provider_named(provider_name).parse_webhook(body, headers)

    with transaction.atomic():
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    provider=provider_name,
                    event_id=result.event_id,
                    event_type=result.event_type,
                    payload=result.payload,
                )
        except IntegrityError:
            event = WebhookEvent.objects.select_for_update().get(
                provider=provider_name, event_id=result.event_id
            )
            if event.processed_at:
                return "duplicate event"

        outcome = _apply(provider_name, result)
        event.processed_at = timezone.now()
        event.outcome = outcome
        event.save(update_fields=["processed_at", "outcome"])
    logger.info("Webhook %s %s: %s", provider_name, result.event_id, outcome)
    return outcome


def _apply(provider_name, result):
    if result.outcome == "ignored":
        return "ignored"
    payment = Payment.objects.filter(
        provider=provider_name, provider_reference=result.provider_reference
    ).first()
    if payment is None:
        return "unknown payment"
    if result.outcome == "succeeded":
        return mark_succeeded(
            payment, amount=result.amount, currency=result.currency, payload=result.payload
        )
    return mark_failed(payment, result.payload)
