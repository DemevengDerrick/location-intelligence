"""The staff order queue and order page (FR-36, FR-37)."""

from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone, translation

from apps.analysis.models import AnalysisRun, ModuleResult, ModuleStatus
from apps.core.audit import log_action
from apps.orders import service_levels
from apps.orders.models import Order, OrderStatus
from apps.orders.testing import make_order

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def at(text):
    return timezone.make_aware(datetime.fromisoformat(text))


@pytest.mark.parametrize(
    ("paid", "due"),
    [
        ("2026-10-26 10:00", "2026-10-29 10:00"),  # Monday → Thursday
        ("2026-10-29 10:00", "2026-11-03 10:00"),  # Thursday → Tuesday, over the weekend
        ("2026-10-31 15:00", "2026-11-05 00:00"),  # Saturday: counting starts on Monday
    ],
)
def test_desk_reports_are_due_three_business_days_after_payment(customer, paid, due):
    order = make_order(customer, status=OrderStatus.PROCESSING, paid_at=at(paid))
    assert service_levels.due_at(order) == at(due)


@pytest.mark.parametrize(
    ("paid", "now", "late"),
    [
        ("2026-10-26 10:00", "2026-10-29 09:59", False),
        ("2026-10-26 10:00", "2026-10-29 10:01", True),
        ("2026-10-31 15:00", "2026-11-04 23:00", False),
        ("2026-10-31 15:00", "2026-11-05 00:01", True),
    ],
)
def test_overdue_flag_and_queue_filter_agree(customer, paid, now, late):
    order = make_order(customer, status=OrderStatus.IN_REVIEW, paid_at=at(paid))
    assert service_levels.is_overdue(order, now=at(now)) is late
    filtered = Order.objects.filter(service_levels.overdue_filter(now=at(now)))
    assert filtered.filter(pk=order.pk).exists() is late


def test_delivered_and_field_orders_are_never_flagged(customer):
    long_ago = timezone.now() - timedelta(days=30)
    delivered = make_order(customer, status=OrderStatus.DELIVERED, paid_at=long_ago)
    field = make_order(customer, status=OrderStatus.PROCESSING, paid_at=long_ago)
    field.tier = "field"
    field.save()
    assert not service_levels.is_overdue(delivered)
    assert not service_levels.is_overdue(field)  # no target for the field tier yet
    assert not Order.objects.filter(service_levels.overdue_filter()).exists()


@pytest.fixture
def admin_client(client, make_user):
    client.force_login(make_user("analyst@example.com", role="analyst", is_staff=True))
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    return client


def test_queue_filters_late_orders_and_regions(admin_client, customer):
    late = make_order(
        customer, status=OrderStatus.IN_REVIEW, paid_at=timezone.now() - timedelta(days=10)
    )
    on_time = make_order(customer, status=OrderStatus.PROCESSING, paid_at=timezone.now())
    late.parcels.update(region="Littoral")
    on_time.parcels.update(region="Centre")
    url = reverse("admin:orders_order_changelist")

    page = admin_client.get(url).content.decode()
    assert "late" in page and "Littoral" in page

    flagged = admin_client.get(url, {"overdue": "yes"}).context["cl"].result_list
    assert [o.pk for o in flagged] == [late.pk]
    centre = admin_client.get(url, {"region": "Centre"}).context["cl"].result_list
    assert [o.pk for o in centre] == [on_time.pk]
    recent = admin_client.get(url, {"age": "1"}).context["cl"].result_list
    assert [o.pk for o in recent] == [on_time.pk]


def test_order_page_shows_modules_audit_log_and_tools(admin_client, customer):
    order = make_order(customer, status=OrderStatus.IN_REVIEW, paid_at=timezone.now())
    parcel = order.parcels.get()
    run = AnalysisRun.objects.create(parcel=parcel)
    ModuleResult.objects.create(run=run, module="terrain", status=ModuleStatus.OK)
    ModuleResult.objects.create(
        run=run, module="flood", status=ModuleStatus.FAILED, error="TimeoutError: JRC"
    )
    log_action("order.status", target=order, data={"to": "in_review"})
    log_action("parcel.boundary_saved", target=parcel, data={"area_m2": 1600})

    html = admin_client.get(reverse("admin:orders_order_change", args=[order.pk])).content.decode()
    assert "TimeoutError: JRC" in html and "terrain" in html
    assert "parcel.boundary_saved" in html and "order.status" in html
    assert reverse("admin:parcels_parcel_geometry", args=[parcel.pk]) in html
    assert "Edit the boundary" in html
