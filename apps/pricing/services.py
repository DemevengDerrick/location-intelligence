from dataclasses import dataclass
from decimal import Decimal

from .models import Product, ProductKind


@dataclass(frozen=True)
class PricedProduct:
    product: Product
    currency: str
    amount: Decimal | None  # None when no price is set for this currency


def priced_tiers(currency):
    """Active tiers in display order, each with its price in `currency`."""
    tiers = Product.objects.filter(kind=ProductKind.TIER, is_active=True).prefetch_related("prices")
    result = []
    for product in tiers:
        price = next((p for p in product.prices.all() if p.currency == currency), None)
        result.append(PricedProduct(product, currency, price.amount if price else None))
    return result
