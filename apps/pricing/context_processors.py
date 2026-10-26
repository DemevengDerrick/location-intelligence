from apps.accounts.models import Currency

from .currency import get_currency


def currency(request):
    return {"CURRENCY": get_currency(request), "CURRENCIES": Currency.values}
