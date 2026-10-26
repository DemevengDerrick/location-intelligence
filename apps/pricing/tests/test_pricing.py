from decimal import Decimal

import pytest

from apps.pricing.models import ProductPrice
from apps.pricing.templatetags.money import format_money

pytestmark = pytest.mark.django_db


def _normalise(text):
    """Babel uses narrow and non-breaking spaces as separators."""
    return text.replace(" ", " ").replace("\xa0", " ")


@pytest.mark.parametrize(
    "amount, currency, language, expected",
    [
        (Decimal("10000"), "XAF", "fr", "10 000 FCFA"),
        (Decimal("10000"), "XAF", "en", "FCFA 10,000"),
        (Decimal("15"), "EUR", "fr", "15,00 €"),
        (Decimal("23"), "CAD", "en", "CA$23.00"),
    ],
)
def test_money_is_formatted_per_locale(amount, currency, language, expected):
    assert _normalise(format_money(amount, currency, language)) == expected


def test_desk_report_launches_at_10000_xaf():
    price = ProductPrice.objects.get(product__code="desk", currency="XAF")
    assert price.amount == Decimal("10000")


def test_pricing_page_defaults_to_xaf(client):
    html = _normalise(client.get("/fr/tarifs/").content.decode())
    assert "10 000 FCFA" in html


def test_currency_choice_changes_prices_and_persists(client):
    response = client.post("/currency/", {"currency": "EUR", "next": "/en/pricing/"})
    assert response.status_code == 302
    assert response.url == "/en/pricing/"
    assert client.cookies["currency"].value == "EUR"

    html = _normalise(client.get("/en/pricing/").content.decode())
    assert "€15.00" in html
    assert "FCFA" not in html.split("<main", 1)[1].split("</main>", 1)[0]


def test_currency_choice_is_saved_on_the_account(client, customer):
    client.force_login(customer)
    client.post("/currency/", {"currency": "CAD", "next": "/en/"})
    customer.refresh_from_db()
    assert customer.currency == "CAD"


def test_invalid_currency_and_offsite_redirect_are_ignored(client):
    response = client.post("/currency/", {"currency": "BTC", "next": "https://evil.example/"})
    assert response.url == "/"
    assert "currency" not in response.cookies


def test_missing_price_shows_price_on_request(client):
    ProductPrice.objects.filter(product__code="field", currency="USD").delete()
    client.cookies["currency"] = "USD"
    html = client.get("/en/pricing/").content.decode()
    assert "Price on request" in html
