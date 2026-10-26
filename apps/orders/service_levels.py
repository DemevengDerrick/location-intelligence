"""Service-level targets (FR-36): business days from payment to delivery, per tier.

Admin-editable in SiteSetting "service_levels" ({"desk": 3}); a tier without a number has no
target and is never flagged. Business days are Monday to Friday; public holidays are not
counted yet.
"""

from datetime import timedelta

from django.utils import timezone

from apps.core.site_settings import get_setting

from .models import OrderStatus

SETTING_KEY = "service_levels"
DEFAULTS = {"desk": 3}
# Orders still being worked on: the target applies only to these.
OPEN = (
    OrderStatus.PAID,
    OrderStatus.NEEDS_GEOREFERENCING,
    OrderStatus.PROCESSING,
    OrderStatus.IN_REVIEW,
)


def target_days(tier):
    stored = get_setting(SETTING_KEY, None) or DEFAULTS
    days = stored.get(tier)
    return int(days) if days not in (None, "") else None


def add_business_days(moment, days):
    """`moment` plus `days` weekdays, at the same time of day. Orders paid at the weekend
    start counting on Monday at midnight."""
    if moment.weekday() >= 5:
        moment = (moment + timedelta(days=7 - moment.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    while days > 0:
        moment += timedelta(days=1)
        if moment.weekday() < 5:
            days -= 1
    return moment


def subtract_business_days(moment, days):
    while days > 0:
        moment -= timedelta(days=1)
        if moment.weekday() < 5:
            days -= 1
    return moment


def due_at(order):
    days = target_days(order.tier)
    if days is None or order.paid_at is None:
        return None
    return add_business_days(timezone.localtime(order.paid_at), days)


def is_overdue(order, now=None):
    due = due_at(order)
    return order.status in OPEN and due is not None and (now or timezone.now()) > due


def overdue_filter(now=None):
    """Query conditions for open orders past their target, one Q per tier with a target."""
    from django.db.models import Q

    now = timezone.localtime(now or timezone.now())
    condition = Q(pk__in=[])
    stored = get_setting(SETTING_KEY, None) or DEFAULTS
    for tier, days in stored.items():
        if days in (None, ""):
            continue
        cutoff = subtract_business_days(now, int(days))
        condition |= Q(tier=tier, paid_at__lt=cutoff)
    return Q(status__in=OPEN) & condition
