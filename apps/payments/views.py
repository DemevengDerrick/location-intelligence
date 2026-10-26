from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.orders.models import Order, OrderStatus

from . import services
from .models import DiscountCode, Payment, PaymentMethod, PaymentPurpose, PaymentStatus
from .providers import InvalidSignature, available_methods
from .providers.demo import DemoProvider
from .webhooks import handle_webhook


def _session_code_key(order):
    return f"discount:{order.public_id}"


def _applied_code(request, order):
    code_id = request.session.get(_session_code_key(order))
    return DiscountCode.objects.filter(pk=code_id).first() if code_id else None


@login_required
@ratelimit(key="user", rate="20/m", method="POST", block=False)
def pay(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, customer=request.user)
    code = _applied_code(request, order)

    if request.method == "POST":
        if order.status != OrderStatus.SUBMITTED or getattr(request, "limited", False):
            if order.status == OrderStatus.SUBMITTED:
                messages.error(request, _("Too many attempts. Please wait a minute."))
            return redirect("payments:pay", public_id=public_id)
        action = request.POST.get("action")
        try:
            if action == "apply_code":
                code = services.find_discount(request.POST.get("code"))
                request.session[_session_code_key(order)] = code.pk
                messages.success(request, _("Discount code applied."))
                return redirect("payments:pay", public_id=public_id)
            if action == "remove_code":
                request.session.pop(_session_code_key(order), None)
                return redirect("payments:pay", public_id=public_id)
            method = request.POST.get("method")
            if method not in available_methods():
                raise services.PaymentError(_("Choose a payment method."))
            return HttpResponseRedirect(services.start_payment(order, method, code, request))
        except services.PaymentError as exc:
            messages.error(request, str(exc))
            return redirect("payments:pay", public_id=public_id)

    options = []
    for method in available_methods():
        option = {
            "method": method,
            "label": PaymentMethod(method).label,
            "quote": None,
            "error": "",
        }
        try:
            option["quote"] = services.quote(order, method, code)
        except services.PaymentError as exc:
            option["error"] = str(exc)
        options.append(option)
    return render(
        request,
        "payments/pay.html",
        {
            "order": order,
            "options": options,
            "code": code,
            "demo_mode": settings.PAYMENTS_DEMO_MODE,
            "pending": order.payments.filter(status=PaymentStatus.PENDING).exists(),
        },
    )


@login_required
@ratelimit(key="user", rate="20/m", method="POST", block=False)
def upgrade(request, public_id):
    """Pay the difference to add field verification to a desk report (FR-20)."""
    order = get_object_or_404(Order, public_id=public_id, customer=request.user)
    if not services.can_upgrade(order):
        return redirect("portal:order", public_id=public_id)
    if request.method == "POST" and not getattr(request, "limited", False):
        method = request.POST.get("method")
        try:
            if method not in available_methods():
                raise services.PaymentError(_("Choose a payment method."))
            url = services.start_payment(
                order, method, None, request, purpose=PaymentPurpose.UPGRADE
            )
            return HttpResponseRedirect(url)
        except services.PaymentError as exc:
            messages.error(request, str(exc))
            return redirect("payments:upgrade", public_id=public_id)

    options = []
    for method in available_methods():
        option = {
            "method": method,
            "label": PaymentMethod(method).label,
            "quote": None,
            "error": "",
        }
        try:
            option["quote"] = services.upgrade_quote(order, method)
        except services.PaymentError as exc:
            option["error"] = str(exc)
        options.append(option)
    return render(
        request,
        "payments/upgrade.html",
        {"order": order, "options": options, "demo_mode": settings.PAYMENTS_DEMO_MODE},
    )


def _own_payment(request, public_id):
    if not request.user.is_authenticated:
        raise Http404
    return get_object_or_404(
        Payment.objects.select_related("order"), public_id=public_id, order__customer=request.user
    )


def payment_return(request, public_id):
    """Where the provider sends the customer back. It only *shows* the status: the order is
    marked paid by the webhook, never by this redirect (FR-14)."""
    payment = _own_payment(request, public_id)
    template = (
        "payments/_status.html" if request.headers.get("HX-Request") else "payments/return.html"
    )
    return render(request, template, {"payment": payment, "order": payment.order})


def demo_checkout(request, public_id):
    """Stand-in for a provider's hosted checkout (card or mobile money) in demo mode."""
    if not settings.PAYMENTS_DEMO_MODE:
        raise Http404
    payment = _own_payment(request, public_id)
    if request.method == "POST" and payment.status == PaymentStatus.PENDING:
        outcome = "succeeded" if request.POST.get("decision") == "approve" else "failed"
        provider = DemoProvider()
        body, headers = provider.build_event(payment, outcome)
        handle_webhook(provider.name, body, headers)  # same path as a real webhook
        return redirect("payments:return", public_id=public_id)
    return render(request, "payments/demo_checkout.html", {"payment": payment})


# --- Webhooks (no CSRF: authenticated by provider signatures) ---------------------------


def _webhook(provider_name, request):
    try:
        outcome = handle_webhook(provider_name, request.body, request.headers)
    except InvalidSignature:
        return HttpResponseBadRequest("invalid signature")
    return HttpResponse(outcome, content_type="text/plain")


@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="300/m", block=True)
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise Http404
    return _webhook("stripe", request)


@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="300/m", block=True)
def demo_webhook(request):
    if not settings.PAYMENTS_DEMO_MODE:
        raise Http404
    return _webhook("fake", request)
