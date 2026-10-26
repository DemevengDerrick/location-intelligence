"""The five-step order form (FR-6): locate, details, tier, account, review."""

import json
from dataclasses import asdict

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import Group
from django.contrib.auth.views import redirect_to_login
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from apps.accounts import roles
from apps.core.maps import basemap_url, preview_config
from apps.gazetteer.boundaries import admin_units_at
from apps.gazetteer.geocoding import default_geocoder
from apps.parcels.choices import InputMethod
from apps.parcels.config import intake_config
from apps.parcels.validation import area_difference_pct
from apps.pricing.currency import get_currency
from apps.pricing.services import priced_tiers

from . import intake
from .intake_forms import AccountForm, DetailsForm, LocateForm, TierForm, geometry_from_json
from .models import Attachment, AttachmentKind, IntakeDraft

STEP_NAMES = {
    1: gettext_lazy("Location"),
    2: gettext_lazy("Details"),
    3: gettext_lazy("Report"),
    4: gettext_lazy("Your details"),
    5: gettext_lazy("Review"),
}


def _step_url(draft, step):
    return reverse("intake:step", args=[draft.token, step])


def _context(request, draft, step, **extra):
    return {
        "draft": draft,
        "step": step,
        "steps": [(n, STEP_NAMES[n]) for n in range(1, IntakeDraft.STEPS + 1)],
        **extra,
    }


def start(request):
    """A short "what you'll need" page; POST starts a new draft."""
    if request.method == "POST":
        draft = intake.start_draft(request, tier=request.POST.get("tier"))
        return redirect(_step_url(draft, 1))
    draft = intake.current_draft(request)
    return render(
        request,
        "orders/intake/start.html",
        {"current": draft, "tier": request.GET.get("tier", "")},
    )


@require_POST
def resume(request):
    draft = intake.resume(request, request.POST.get("token", ""))
    if draft is None:
        return redirect("intake:start")
    return redirect(_step_url(draft, draft.step_reached))


def _open_draft(request, token):
    """get_draft for endpoints that only make sense on an open draft."""
    try:
        return intake.get_draft(request, token)
    except (intake.SignInRequired, intake.AlreadySubmitted) as exc:
        raise Http404 from exc


def step(request, token, number):
    try:
        draft = intake.get_draft(request, token)
    except intake.SignInRequired:
        return redirect_to_login(request.get_full_path())
    except intake.AlreadySubmitted as exc:
        return redirect("payments:pay", public_id=exc.order.public_id)
    if not 1 <= number <= IntakeDraft.STEPS:
        raise Http404
    if number > draft.step_reached:
        return redirect(_step_url(draft, draft.step_reached))
    handler = {1: _locate, 2: _details, 3: _tier, 4: _account, 5: _review}[number]
    return handler(request, draft)


# --- Step 1 ------------------------------------------------------------------------------


def _locate(request, draft):
    form = LocateForm(
        request.POST or None,
        request.FILES or None,
        draft=draft,
        initial={"method": draft.input_method or InputMethod.PIN},
    )
    if request.method == "POST" and form.is_valid():
        _save_location(draft, form, request.user)
        intake.advance(draft, 1)
        draft.save()
        return redirect(_step_url(draft, 2))

    config = {
        "token": str(draft.token),
        "basemapUrl": basemap_url(),
        "attribution": settings.BASEMAP_ATTRIBUTION,
        "searchUrl": reverse("intake:search"),
        "geometry": json.loads(draft.geometry.geojson) if draft.geometry else None,
        "pin": json.loads(draft.pin.geojson) if draft.pin else None,
        "method": form["method"].value(),
        "messages": {
            "noResults": _("No place found. Try another spelling or a nearby town."),
            "searching": _("Searching…"),
        },
    }
    return render(
        request,
        "orders/intake/step_locate.html",
        _context(request, draft, 1, form=form, map_config=config),
    )


def _save_location(draft, form, user):
    method = form.cleaned_data["method"]
    checked = form.checked
    draft.input_method = method
    draft.location_warnings = checked.warnings if checked else []
    draft.is_approximate = bool(checked and checked.is_approximate)
    if method == InputMethod.SITE_PLAN:
        # The analyst digitizes the boundary later (Journey B); keep any rough pin only.
        draft.geometry = None
        draft.computed_area_m2 = None
        draft.pin = _point_or_none(form)
        upload = form.cleaned_data.get("site_plan")
        if upload:
            draft.attachments.filter(kind=AttachmentKind.SITE_PLAN).delete()
            _attach(draft, upload, AttachmentKind.SITE_PLAN, form.site_plan_mime, user)
    else:
        draft.geometry = checked.geometry
        # A pin's 30 m circle is not the parcel: its area means nothing to the customer.
        draft.computed_area_m2 = None if checked.is_approximate else checked.area_m2
        draft.pin = _point_or_none(form) if method == InputMethod.PIN else None

    location = draft.geometry or draft.pin
    if location is not None:
        units = admin_units_at(location)
        draft.region = draft.region or units.region
        draft.commune = draft.commune or units.commune


def _point_or_none(form):
    geom = geometry_from_json(form.cleaned_data.get("geometry"))
    return geom if geom is not None and geom.geom_type == "Point" else None


def _attach(draft, upload, kind, mime, user):
    return Attachment.objects.create(
        draft=draft,
        kind=kind,
        file=upload,
        original_name=upload.name[:255],
        content_type=mime or "",
        size_bytes=upload.size,
        uploaded_by=user if user.is_authenticated else None,
    )


@require_GET
@ratelimit(key="ip", rate="30/m", block=False)
def search(request):
    """Place-name search for the map (gazetteer first, then OSM Nominatim)."""
    if getattr(request, "limited", False):
        return JsonResponse({"results": [], "error": "rate_limited"}, status=429)
    query = request.GET.get("q", "").strip()[:100]
    if len(query) < 3:
        return JsonResponse({"results": []})
    results = default_geocoder().search(query, translation.get_language() or "fr", limit=6)
    return JsonResponse({"results": [asdict(r) for r in results]})


# --- Step 2 ------------------------------------------------------------------------------


def _details(request, draft):
    form = DetailsForm(request.POST or None, request.FILES or None, instance=draft)
    if request.method == "POST" and form.is_valid():
        draft = form.save(commit=False)
        for upload, mime in zip(form.cleaned_data["documents"], form.mimes, strict=True):
            kind = AttachmentKind.PHOTO if mime.startswith("image/") else AttachmentKind.DOCUMENT
            _attach(draft, upload, kind, mime, request.user)
        intake.advance(draft, 2)
        draft.save()
        return redirect(_step_url(draft, 3))
    return render(
        request,
        "orders/intake/step_details.html",
        _context(
            request,
            draft,
            2,
            form=form,
            documents=draft.attachments.exclude(kind=AttachmentKind.SITE_PLAN),
            area_check=_area_check(draft.computed_area_m2, draft.stated_area_m2),
            approximate=draft.is_approximate,
        ),
    )


def _area_check(computed, stated):
    """FR-11: computed vs stated area, flagged above the configured difference."""
    if not computed:
        return None
    diff = area_difference_pct(computed, stated)
    return {
        "computed": computed,
        "stated": stated,
        "difference": diff,
        "flagged": diff is not None and abs(diff) > intake_config().area_difference_pct,
        "threshold": intake_config().area_difference_pct,
    }


@require_POST
def area_check(request, token):
    """HTMX partial: recompute the area comparison as the customer types."""
    draft = _open_draft(request, token)
    try:
        value = float(request.POST.get("stated_area", "").replace(",", ".").replace(" ", ""))
    except ValueError:
        value = None
    if value is not None and request.POST.get("stated_area_unit") == "ha":
        value *= 10_000
    return render(
        request,
        "orders/intake/_area_check.html",
        {
            "area_check": _area_check(draft.computed_area_m2, value),
            "approximate": draft.is_approximate,
        },
    )


@require_POST
def delete_attachment(request, token, pk):
    draft = _open_draft(request, token)
    get_object_or_404(Attachment, pk=pk, draft=draft, order__isnull=True).delete()
    return redirect(_step_url(draft, 2))


# --- Step 3 ------------------------------------------------------------------------------


def _tier(request, draft):
    draft.currency = get_currency(request)  # follows the site's currency switcher
    form = TierForm(request.POST or None, instance=draft)
    if request.method == "POST" and form.is_valid():
        draft = form.save(commit=False)
        if intake.draft_price(draft) is None:
            form.add_error(
                None,
                _("This report is not sold in %(currency)s yet. Choose another currency.")
                % {"currency": draft.currency},
            )
        else:
            intake.advance(draft, 3)
            draft.save()
            return redirect(_step_url(draft, 4))
    prices = {t.product.code: t.amount for t in priced_tiers(draft.currency)}
    tier_options = [(choice, prices.get(choice.data["value"])) for choice in form["tier"]]
    return render(
        request,
        "orders/intake/step_tier.html",
        _context(request, draft, 3, form=form, tier_options=tier_options),
    )


# --- Step 4 ------------------------------------------------------------------------------


def _account(request, draft):
    initial = {"contact_name": draft.contact_name, "contact_phone": draft.contact_phone}
    form = AccountForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        if not request.user.is_authenticated:
            user = _create_customer(request, data)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            intake.remember(request, draft)  # the session was rotated on login
            draft.user = user
        draft.contact_name = data["contact_name"]
        draft.contact_phone = data["contact_phone"]
        draft.terms_version = intake.current_terms_version()
        draft.terms_accepted_at = timezone.now()
        _update_profile(draft.user, data)
        intake.advance(draft, 4)
        draft.save()
        return redirect(_step_url(draft, 5))
    login_url = f"{reverse('account_login')}?next={_step_url(draft, 4)}"
    return render(
        request,
        "orders/intake/step_account.html",
        _context(request, draft, 4, form=form, login_url=login_url),
    )


def _create_customer(request, data):
    """Create the account during checkout (FR-17). Without a password, sign-in is by email code."""
    first, _sep, last = data["contact_name"].partition(" ")
    user = get_user_model().objects.create_user(
        email=data["email"],
        password=data.get("password") or None,
        first_name=first[:150],
        last_name=last[:150],
        phone=data.get("contact_phone", ""),
        language=translation.get_language() or "fr",
        currency=get_currency(request),
    )
    if not data.get("password"):
        user.set_unusable_password()
        user.save(update_fields=["password"])
    EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=False)
    user.groups.add(Group.objects.get_or_create(name=roles.CUSTOMER)[0])
    return user


def _update_profile(user, data):
    changed = []
    if data.get("contact_phone") and not user.phone:
        user.phone = data["contact_phone"]
        changed.append("phone")
    if not user.first_name and data.get("contact_name"):
        first, _sep, last = data["contact_name"].partition(" ")
        user.first_name, user.last_name = first[:150], last[:150]
        changed += ["first_name", "last_name"]
    if changed:
        user.save(update_fields=changed)


# --- Step 5 ------------------------------------------------------------------------------


def _review(request, draft):
    price = intake.draft_price(draft)
    if request.method == "POST" and draft.user_id == request.user.id and price is not None:
        order = intake.submit(draft, request)
        return redirect("payments:pay", public_id=order.public_id)
    return render(
        request,
        "orders/intake/step_review.html",
        _context(
            request,
            draft,
            5,
            price=price,
            area_check=_area_check(draft.computed_area_m2, draft.stated_area_m2),
            approximate=draft.is_approximate,
            documents=draft.attachments.all(),
            map_config=preview_config(geometry=draft.geometry, pin=draft.pin),
        ),
    )
