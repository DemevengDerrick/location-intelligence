from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.orders.models import Order
from apps.payments.models import Payment, PaymentProviderName

pytestmark = pytest.mark.django_db


def test_provider_reference_is_unique_per_provider(customer):
    order = Order.objects.create(customer=customer)
    fields = {"order": order, "amount": Decimal("50000"), "currency": "XAF"}
    Payment.objects.create(provider=PaymentProviderName.STRIPE, provider_reference="cs_1", **fields)
    # The same reference from another provider is a different transaction.
    Payment.objects.create(
        provider=PaymentProviderName.MOBILE_MONEY, provider_reference="cs_1", **fields
    )

    with pytest.raises(IntegrityError):
        Payment.objects.create(
            provider=PaymentProviderName.STRIPE, provider_reference="cs_1", **fields
        )
