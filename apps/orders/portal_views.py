"""Customer portal (FR-17–FR-21): my orders, order page, messages, account settings.

Every query is scoped to the signed-in customer, so changing an ID in the URL gives a 404.
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.analysis.style import RATING_COLOURS, RATING_ICONS, RATING_WORDS
from apps.core.maps import preview_config
from apps.core.models import AuditLog
from apps.payments.models import PaymentStatus
from apps.payments.services import can_upgrade
from apps.pricing.currency import set_currency_cookie

from .models import IntakeDraft, Message, Order, OrderStatus
from .portal_forms import MessageForm, ProfileForm


def _my_order(request, public_id):
    return get_object_or_404(Order, public_id=public_id, customer=request.user)


@login_required
def order_list(request):
    orders = Order.objects.filter(customer=request.user).order_by("-created_at")
    drafts = IntakeDraft.objects.filter(
        user=request.user, order__isnull=True, step_reached__gt=1
    ).order_by("-updated_at")[:3]
    return render(request, "portal/order_list.html", {"orders": orders, "drafts": drafts})


def _timeline(order):
    """(date, status label) for every status the order went through, oldest first."""
    entries = AuditLog.objects.filter(
        action="order.status",
        target_type=ContentType.objects.get_for_model(Order),
        target_id=str(order.pk),
    ).order_by("created_at")
    return [(order.created_at, OrderStatus.SUBMITTED.label)] + [
        (entry.created_at, OrderStatus(entry.data["to"]).label) for entry in entries
    ]


def _map_config(parcel):
    if parcel is None or parcel.geometry is None:
        return None
    if parcel.is_approximate:  # show the pin, not the analysis circle around it
        return preview_config(pin=parcel.geometry.centroid)
    return preview_config(geometry=parcel.geometry)


@login_required
def order_detail(request, public_id):
    order = _my_order(request, public_id)
    # Staff replies count as read once the customer has opened the order.
    order.messages.exclude(author=request.user).filter(read_at__isnull=True).update(
        read_at=timezone.now()
    )
    parcel = order.parcels.first()
    return render(
        request,
        "portal/order_detail.html",
        {
            "order": order,
            "parcel": parcel,
            "timeline": _timeline(order),
            "attachments": order.attachments.all(),
            "payments": order.payments.filter(
                status__in=[PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED]
            ),
            "thread": order.messages.select_related("author"),
            "message_form": MessageForm(),
            "can_upgrade": can_upgrade(order),
            "map_config": _map_config(parcel),
            **_report_context(order),
        },
    )


def _report_context(order):
    """The latest delivered version: its summary in the visitor's language and both PDFs."""
    report = getattr(order, "report", None)
    if report is None:
        return {}
    versions = list(report.versions.order_by("-number", "language"))
    if not versions:
        return {"report": report}
    latest = [v for v in versions if v.number == versions[0].number]
    language = translation.get_language() or "fr"
    summary = [
        {
            "label": RATING_WORDS[f["rating"]],
            "colour": RATING_COLOURS[f["rating"]],
            "icon": RATING_ICONS[f["rating"]],
            "sentence": f["text"].get(language) or f["text"].get("fr", ""),
        }
        for f in latest[0].content.get("findings", [])
        if not f.get("hidden")
    ]
    return {"report": report, "versions": versions, "latest_versions": latest, "summary": summary}


@login_required
@require_POST
@ratelimit(key="user", rate="20/h", block=False)
def post_message(request, public_id):
    order = _my_order(request, public_id)
    form = MessageForm(request.POST)
    if getattr(request, "limited", False):
        messages.error(request, _("Too many messages. Please wait before sending another."))
    elif form.is_valid():
        Message.objects.create(order=order, author=request.user, body=form.cleaned_data["body"])
        messages.success(request, _("Message sent. We usually reply within one business day."))
    else:
        messages.error(request, _("Write a message before sending."))
    return redirect(reverse("portal:order", args=[order.public_id]) + "#messages")


@login_required
def attachment_download(request, public_id, pk):
    order = _my_order(request, public_id)
    attachment = get_object_or_404(order.attachments, pk=pk)
    return HttpResponseRedirect(attachment.file.url)  # short-lived signed URL (NFR-8)


@login_required
def account(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, _("Your details have been saved."))
        # Switch the site to the chosen language and currency straight away.
        with translation.override(user.language):
            response = redirect(reverse("portal:account"))
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME, user.language, max_age=settings.LANGUAGE_COOKIE_AGE
        )
        set_currency_cookie(response, user.currency)
        return response
    return render(request, "portal/account.html", {"form": form})
