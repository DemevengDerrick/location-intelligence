"""The `PaymentProvider` interface (FR-13): swap providers without touching business logic."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

# Currencies Stripe (and most providers) express without minor units.
ZERO_DECIMAL = {"XAF", "XOF"}


def to_minor(amount: Decimal, currency: str) -> int:
    return int(amount) if currency.upper() in ZERO_DECIMAL else int(amount * 100)


def from_minor(value: int, currency: str) -> Decimal:
    return Decimal(value) if currency.upper() in ZERO_DECIMAL else Decimal(value) / 100


class InvalidSignature(Exception):
    """The webhook could not be authenticated; nothing must change."""


@dataclass(frozen=True)
class CheckoutSession:
    provider_reference: str
    redirect_url: str


@dataclass(frozen=True)
class WebhookResult:
    event_id: str
    event_type: str
    provider_reference: str
    outcome: str  # "succeeded", "failed" or "ignored"
    amount: Decimal | None = None
    currency: str = ""
    payload: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def create_checkout(
        self, payment, *, success_url, cancel_url, customer_email, language, description
    ) -> CheckoutSession:
        """Start a hosted payment and return where to send the customer."""

    @abstractmethod
    def parse_webhook(self, body: bytes, headers) -> WebhookResult:
        """Verify the signature and translate the event. Raise InvalidSignature if it fails."""

    @abstractmethod
    def refund(self, payment, amount: Decimal) -> str:
        """Refund `amount` of the payment and return the provider's refund reference."""
