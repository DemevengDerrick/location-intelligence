"""Helpers shared by tests."""

from decimal import Decimal

from apps.parcels.models import InputMethod, Parcel
from apps.parcels.testing import DOUALA, square_m

from .models import Order


def make_order(customer, *, currency="XAF", price="10000", geometry=True, **fields):
    order = Order.objects.create(
        customer=customer, tier="desk", currency=currency, price_amount=Decimal(price), **fields
    )
    Parcel.objects.create(
        order=order,
        geometry=square_m(*DOUALA, 40) if geometry else None,
        input_method=InputMethod.DRAWN if geometry else InputMethod.SITE_PLAN,
        quartier="Bonamoussadi",
        commune="Douala V",
    )
    return order
