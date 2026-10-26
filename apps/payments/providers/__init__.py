"""Which provider handles which payment method.

- Demo mode (PAYMENTS_DEMO_MODE): every method uses the demo provider; no money moves.
- Card: Stripe Checkout when STRIPE_SECRET_KEY is set.
- Mobile money: unavailable outside demo mode until an aggregator is chosen and wired in
  as another PaymentProvider.
"""

from django.conf import settings

from ..models import PaymentMethod
from .base import InvalidSignature, PaymentProvider
from .demo import DemoProvider, ManualProvider
from .stripe_provider import StripeProvider

__all__ = ["InvalidSignature", "PaymentProvider", "checkout_provider", "provider_named"]


def provider_named(name) -> PaymentProvider:
    return {"stripe": StripeProvider, "fake": DemoProvider, "manual": ManualProvider}[name]()


def checkout_provider(method) -> PaymentProvider | None:
    if settings.PAYMENTS_DEMO_MODE:
        return DemoProvider()
    if method == PaymentMethod.CARD and settings.STRIPE_SECRET_KEY:
        return StripeProvider()
    return None


def available_methods():
    return [m for m in (PaymentMethod.CARD, PaymentMethod.MOBILE_MONEY) if checkout_provider(m)]
