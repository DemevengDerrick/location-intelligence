"""FR-43: the analyst's optional "suggest wording" button."""

import pytest
from django.urls import reverse

from apps.orders.models import OrderStatus
from apps.orders.testing import make_order
from apps.reports import wording
from apps.reports.models import Report

pytestmark = pytest.mark.django_db


@pytest.fixture
def report(customer):
    order = make_order(customer, status=OrderStatus.IN_REVIEW)
    return Report.objects.create(order=order, draft={"findings": [], "note": {"fr": "", "en": ""}})


@pytest.fixture
def analyst_client(client, make_user):
    client.force_login(make_user("analyst@example.com", role="analyst", is_staff=True))
    return client


def test_suggestion_is_returned_for_the_analyst_to_accept(
    report, analyst_client, settings, monkeypatch
):
    settings.ANTHROPIC_API_KEY = "test-key"
    calls = []
    monkeypatch.setattr(
        wording, "suggest", lambda text, language: calls.append((text, language)) or "Clearer."
    )
    review = analyst_client.get(reverse("admin:reports_report_review", args=[report.pk]))
    assert "suggest-config" in review.content.decode()
    response = analyst_client.post(
        reverse("admin:reports_report_suggest", args=[report.pk]),
        {"text": "The parcel is flood prone.", "language": "en"},
    )
    assert response.json() == {"suggestion": "Clearer."}
    assert calls == [("The parcel is flood prone.", "en")]
    report.refresh_from_db()
    assert report.draft["findings"] == []  # nothing changes until the analyst accepts


def test_no_button_and_no_call_without_a_key(report, analyst_client, settings):
    settings.ANTHROPIC_API_KEY = ""
    review = analyst_client.get(reverse("admin:reports_report_review", args=[report.pk]))
    assert "suggest-config" not in review.content.decode()
    response = analyst_client.post(
        reverse("admin:reports_report_suggest", args=[report.pk]), {"text": "x", "language": "fr"}
    )
    assert response.status_code == 503


def test_customers_cannot_ask_for_suggestions(report, client, customer):
    client.force_login(customer)
    response = client.post(reverse("admin:reports_report_suggest", args=[report.pk]), {"text": "x"})
    assert response.status_code in (302, 403)
