"""Order-form drafts: access control, pricing and conversion into an Order (FR-6, NFR-4)."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.http import Http404
from django.utils import timezone, translation

from apps.core.audit import log_action
from apps.pages.models import Page, PageSlug
from apps.parcels.models import Parcel
from apps.pricing.currency import get_currency
from apps.pricing.models import ProductPrice

from .models import IntakeDraft, Order, OrderStatus, Tier

SESSION_KEY = "intake_drafts"


def _cutoff():
    return timezone.now() - timedelta(days=IntakeDraft.EXPIRY_DAYS)


def _open_drafts():
    return IntakeDraft.objects.filter(order__isnull=True, updated_at__gte=_cutoff())


def _session_tokens(request):
    return request.session.get(SESSION_KEY, [])


def remember(request, draft):
    tokens = [t for t in _session_tokens(request) if t != str(draft.token)]
    request.session[SESSION_KEY] = [str(draft.token), *tokens][:5]


def start_draft(request, tier=None):
    if not request.session.session_key:
        request.session.save()
    user = request.user if request.user.is_authenticated else None
    draft = IntakeDraft.objects.create(
        user=user,
        session_key=request.session.session_key,
        tier=tier if tier in Tier.values else Tier.DESK,
        currency=get_currency(request),
        report_language=translation.get_language() or "fr",
        contact_name=user.get_full_name() if user else "",
        contact_phone=user.phone if user else "",
    )
    remember(request, draft)
    return draft


def current_draft(request):
    """The customer's most recent open draft, if any."""
    drafts = _open_drafts()
    if request.user.is_authenticated:
        mine = drafts.filter(user=request.user).first()
        if mine:
            return mine
    tokens = _session_tokens(request)
    return drafts.filter(token__in=tokens, user__isnull=True).first() if tokens else None


class SignInRequired(Exception):
    """The draft belongs to an account and the visitor is signed out."""


class AlreadySubmitted(Exception):
    def __init__(self, order):
        super().__init__(str(order))
        self.order = order


def get_draft(request, token):
    """The draft, if this browser or account may open it; 404 otherwise.

    Raises SignInRequired for an account's draft opened while signed out, and
    AlreadySubmitted (with the order) for a draft that has become an order.
    """
    draft = IntakeDraft.objects.filter(token=token, updated_at__gte=_cutoff()).first()
    if draft is None:
        raise Http404
    if draft.user_id:
        if not request.user.is_authenticated:
            raise SignInRequired
        if request.user.id != draft.user_id:
            raise Http404
    elif str(draft.token) not in _session_tokens(request):
        raise Http404
    if draft.is_submitted:
        raise AlreadySubmitted(draft.order)
    if not draft.user_id and request.user.is_authenticated:
        draft.user = request.user  # claim an anonymous draft after signing in
        draft.save(update_fields=["user", "updated_at"])
    return draft


def resume(request, token):
    """Reattach an anonymous draft to this session using the token kept in localStorage."""
    draft = _open_drafts().filter(token=token).first()
    if draft is None:
        return None
    if draft.user_id and draft.user_id != request.user.id:
        return None
    remember(request, draft)
    return draft


def advance(draft, step):
    if draft.step_reached < step + 1:
        draft.step_reached = min(step + 1, IntakeDraft.STEPS)


def draft_price(draft):
    """Tier plus add-ons in the draft's currency, or None if any price is missing."""
    codes = [draft.tier, *draft.add_ons]
    prices = dict(
        ProductPrice.objects.filter(
            product__code__in=codes, product__is_active=True, currency=draft.currency
        ).values_list("product__code", "amount")
    )
    if any(code not in prices for code in codes):
        return None
    return sum((prices[code] for code in codes), Decimal("0"))


def current_terms_version():
    return Page.objects.filter(slug=PageSlug.TERMS).values_list("version", flat=True).first() or ""


@transaction.atomic
def submit(draft, request):
    """Create the Order and Parcel from a completed draft and move its attachments."""
    draft = IntakeDraft.objects.select_for_update().get(pk=draft.pk)
    if draft.is_submitted:
        return draft.order
    price = draft_price(draft)
    if price is None:
        raise ValueError("No price for this tier in the selected currency")

    user = draft.user
    order = Order.objects.create(
        customer=user,
        organization=user.organization,
        status=OrderStatus.SUBMITTED,
        tier=draft.tier,
        add_ons=draft.add_ons,
        currency=draft.currency,
        price_amount=price,
        language=draft.report_language,
        intended_use=draft.intended_use,
        deadline=draft.deadline,
        notes=draft.notes,
        terms_version=draft.terms_version,
        terms_accepted_at=draft.terms_accepted_at,
    )
    Parcel.objects.create(
        order=order,
        geometry=draft.geometry,
        input_method=draft.input_method,
        is_approximate=draft.is_approximate,
        stated_area_m2=draft.stated_area_m2,
        quartier=draft.quartier,
        commune=draft.commune,
        region=draft.region,
        title_number=draft.title_number,
    )
    draft.attachments.update(order=order)
    draft.order = order
    draft.save(update_fields=["order", "updated_at"])
    log_action("order.submitted", actor=user, target=order, request=request)
    return order
