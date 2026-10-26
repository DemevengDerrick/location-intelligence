from django.http import HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import currency


@require_POST
def set_currency(request):
    code = request.POST.get("currency", "")
    next_url = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = "/"
    response = HttpResponseRedirect(next_url)
    if currency.is_valid(code):
        currency.set_currency_cookie(response, code)
        if request.user.is_authenticated and request.user.currency != code:
            request.user.currency = code
            request.user.save(update_fields=["currency"])
    return response
