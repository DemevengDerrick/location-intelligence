from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Currency
from apps.core.models import TimeStampedModel


class ProductKind(models.TextChoices):
    TIER = "tier", _("Tier")
    ADD_ON = "add_on", _("Add-on")


class Product(TimeStampedModel):
    """A sellable tier or add-on. Tier codes match `orders.Tier` values."""

    code = models.SlugField(_("code"), max_length=40, unique=True)
    kind = models.CharField(_("kind"), max_length=8, choices=ProductKind.choices)
    # name, tagline and features are translated (see translation.py).
    name = models.CharField(_("name"), max_length=100)
    tagline = models.CharField(_("tagline"), max_length=200, blank=True)
    features = models.TextField(_("features"), blank=True, help_text=_("One feature per line."))
    sort_order = models.PositiveSmallIntegerField(_("sort order"), default=0)
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ["kind", "sort_order"]

    def __str__(self):
        return self.name

    @property
    def feature_list(self):
        return [line.strip() for line in self.features.splitlines() if line.strip()]


class ProductPrice(TimeStampedModel):
    """Admin-set price per currency (FR-3). Never a live FX conversion."""

    product = models.ForeignKey(
        Product, verbose_name=_("product"), on_delete=models.CASCADE, related_name="prices"
    )
    currency = models.CharField(_("currency"), max_length=3, choices=Currency.choices)
    amount = models.DecimalField(_("amount"), max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = _("price")
        verbose_name_plural = _("prices")
        constraints = [
            models.UniqueConstraint(fields=["product", "currency"], name="unique_product_currency")
        ]

    def __str__(self):
        return f"{self.product.code} {self.amount} {self.currency}"
