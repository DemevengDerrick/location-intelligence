from babel.numbers import format_currency
from django import template
from django.utils import translation

register = template.Library()

# Cameroonian locales give "FCFA" for XAF in both languages.
_LOCALES = {"fr": "fr_CM", "en": "en_CM"}
# en_CM glues the symbol to the number ("FCFA10,000"); FCFA reads better with a space.
_PATTERNS = {("en", "XAF"): "¤\xa0#,##0.00"}


def format_money(amount, currency, language=None):
    language = (language or translation.get_language() or "fr")[:2]
    return format_currency(
        amount,
        currency,
        format=_PATTERNS.get((language, currency)),
        locale=_LOCALES.get(language, "fr_CM"),
    )


@register.filter
def money(amount, currency):
    """{{ amount|money:"XAF" }} → "10 000 FCFA" in French, "FCFA 10,000" in English."""
    if amount is None or amount == "":
        return ""
    return format_money(amount, currency)
