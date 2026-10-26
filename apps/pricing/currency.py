"""The visitor's display currency: cookie first, then the account preference, then XAF."""

from django.conf import settings

from apps.accounts.models import Currency

COOKIE_NAME = "currency"
COOKIE_AGE = 60 * 60 * 24 * 365
DEFAULT = Currency.XAF.value


def is_valid(code):
    return code in Currency.values


def get_currency(request):
    code = request.COOKIES.get(COOKIE_NAME)
    if is_valid(code):
        return code
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and is_valid(user.currency):
        return user.currency
    return DEFAULT


def set_currency_cookie(response, code):
    response.set_cookie(
        COOKIE_NAME,
        code,
        max_age=COOKIE_AGE,
        samesite="Lax",
        secure=getattr(settings, "LANGUAGE_COOKIE_SECURE", False),
    )
