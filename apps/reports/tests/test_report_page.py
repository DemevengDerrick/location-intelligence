"""The interactive report page and shared links (FR-19)."""

import json
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone, translation

from apps.core.models import AuditLog
from apps.orders.models import OrderStatus
from apps.orders.testing import make_order
from apps.reports.models import Report, ReportShare, ReportVersion

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def finding(module, rating="green", **extra):
    return {
        "module": module,
        "computed_rating": rating,
        "rating": rating,
        "override_reason": "",
        "text": {"fr": f"Constat {module}.", "en": f"Finding {module}."},
        "results": {},
        "key": {"fr": f"clé {module}", "en": f"key {module}"},
        "charts": {},
        "maps": {},
        "layers": [],
        "datasets": {},
        "unavailable": False,
        "hidden": False,
        "hidden_reason": "",
        **extra,
    }


SLOPE_LAYER = {
    "id": "slope",
    "type": "image",
    "title": {"fr": "Pente", "en": "Slope"},
    "image": "analysis/run-1/terrain-layer-slope.png",
    "coordinates": [[9.69, 4.06], [9.71, 4.06], [9.71, 4.04], [9.69, 4.04]],
    "opacity": 0.75,
    "visible": True,
    "legend": [
        {"color": "#F7F4D2", "label": {"fr": "Moins de 5°", "en": "Under 5°"}, "shape": "fill"}
    ],
    "hover": {"grid": [[1.5, 2.0], [3.5, None]], "unit": {"fr": "°", "en": "°"}},
}
SERVICES_LAYER = {
    "id": "services",
    "type": "geojson",
    "title": {"fr": "Services", "en": "Services"},
    "data": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [9.701, 4.051]},
                "properties": {
                    "name": "Clinique Necker",
                    "type": {"fr": "Établissement de santé", "en": "Health facility"},
                },
            }
        ],
    },
    "style": {
        "kind": "circle",
        "color": "#0072B2",
        "outline": "#FFFFFF",
        "opacity": 1,
        "width": 5,
        "dash": False,
    },
    "hover": [{"property": "type", "label": {"fr": "Service", "en": "Service"}}],
    "legend": [],
    "visible": True,
}
CHART = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "title": {"text": "Elevation varies by 1.1 m across the parcel", "subtitle": "DEM"},
    "data": {"values": [{"distance": 0, "elevation": 16.1}, {"distance": 10, "elevation": 16.4}]},
    "mark": "line",
}


def delivered(customer, **content_extra):
    order = make_order(customer, status=OrderStatus.DELIVERED)
    report = Report.objects.create(order=order)
    content = {
        "run": None,
        "approximate": False,
        "findings": [
            finding("location", "red"),
            finding(
                "terrain", layers=[SLOPE_LAYER], charts={"profile": {"fr": CHART, "en": CHART}}
            ),
            finding(
                "access",
                layers=[SERVICES_LAYER],
                charts={
                    "services": {
                        "table": {
                            "fr": {
                                "caption": "Services",
                                "columns": ["Destination"],
                                "rows": [["École"]],
                            },
                            "en": {
                                "caption": "Nearest services",
                                "columns": ["Destination"],
                                "rows": [["School"]],
                            },
                        }
                    }
                },
            ),
            finding("demographics", hidden=True),
        ],
        "note": {"fr": "", "en": "Checked on site."},
        **content_extra,
    }
    for language in ("fr", "en"):
        version = ReportVersion(
            report=report,
            number=1,
            language=language,
            content=content,
            approved_at=timezone.now(),
        )
        version.pdf.save(f"test-{language}.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        version.save()
    return report


def page_url(report):
    return reverse("reports:page", args=[report.order.public_id])


def map_config(html, module):
    start = html.index(f'id="map-{module}-config"')
    body = html[html.index(">", start) + 1 : html.index("</script>", start)]
    return json.loads(body)


def test_owner_sees_the_interactive_report(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    response = client.get(page_url(report))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Finding terrain." in html and "Finding access." in html
    assert "Finding demographics." not in html  # hidden by the analyst
    assert "Checked on site." in html
    assert "key access" in html  # the summary tiles
    config = map_config(html, "terrain")
    slope = config["layers"][0]
    assert slope["title"] == "Slope" and slope["legend"][0]["label"] == "Under 5°"
    assert "terrain-layer-slope.png" in slope["url"] and "image" not in slope
    assert slope["hover"]["grid"][1][1] is None
    services = map_config(html, "access")["layers"][0]
    assert services["data"]["features"][0]["properties"]["type"] == "Health facility"
    assert config["parcel"]["type"] == "MultiPolygon"
    assert 'data-vega="vega-terrain-profile"' in html and 'id="vega-terrain-profile"' in html
    assert "Chart data" in html and "16.4" in html  # accessible data table
    assert "Nearest services" in html  # tables render as tables
    assert "Share this report" in html


def test_the_page_follows_the_reader_language(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    with translation.override("fr"):
        html = client.get(page_url(report)).content.decode()
    assert "Constat terrain." in html and "Pente" in html


def test_another_customer_cannot_open_the_report(client, customer, make_user):
    report = delivered(customer)
    client.force_login(make_user(email="other@example.com", role="customer"))
    assert client.get(page_url(report)).status_code == 404


def test_anonymous_visitors_are_sent_to_sign_in(client, customer):
    response = client.get(page_url(delivered(customer)))
    assert response.status_code == 302 and "/accounts/login/" in response.url


def test_staff_can_open_any_report(client, customer, analyst):
    report = delivered(customer)
    analyst.is_staff = True
    analyst.save()
    client.force_login(analyst)
    response = client.get(page_url(report))
    assert response.status_code == 200
    assert "Share this report" not in response.content.decode()  # only the owner shares


def test_no_page_before_delivery(client, customer):
    order = make_order(customer, status=OrderStatus.IN_REVIEW)
    Report.objects.create(order=order)
    client.force_login(customer)
    assert client.get(reverse("reports:page", args=[order.public_id])).status_code == 404


def test_order_page_links_to_the_interactive_report(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    html = client.get(reverse("portal:order", args=[report.order.public_id])).content.decode()
    assert page_url(report) in html and "Open the interactive report" in html


# --- share links ---------------------------------------------------------------------------


def share(client, report, days="30"):
    return client.post(
        reverse("reports:share_create", args=[report.order.public_id]), {"days": days}
    )


def test_owner_creates_a_share_link_that_works_without_an_account(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    assert share(client, report).status_code == 302
    link = ReportShare.objects.get()
    assert link.expires_at - timezone.now() > timedelta(days=29)
    assert AuditLog.objects.filter(action="report.share_created").exists()

    client.logout()
    response = client.get(reverse("reports:shared", args=[link.token]))
    assert response.status_code == 200
    html = response.content.decode()
    assert "Finding terrain." in html
    assert "Share this report" not in html and "Back to the order" not in html
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert response["Referrer-Policy"] == "no-referrer"
    link.refresh_from_db()
    assert link.views == 1
    assert AuditLog.objects.filter(action="report.share_viewed").exists()
    pdf = client.get(reverse("reports:shared_download", args=[link.token, 1, "en"]))
    assert pdf.status_code == 302


def test_unknown_expiry_choices_fall_back_to_the_default(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    share(client, report, days="3650")
    assert ReportShare.objects.get().expires_at - timezone.now() < timedelta(days=31)


def test_revoked_and_expired_links_stop_working(client, customer):
    report = delivered(customer)
    client.force_login(customer)
    share(client, report)
    link = ReportShare.objects.get()
    client.post(reverse("reports:share_revoke", args=[report.order.public_id, link.pk]))
    link.refresh_from_db()
    assert link.revoked_at is not None
    assert AuditLog.objects.filter(action="report.share_revoked").exists()
    assert client.get(reverse("reports:shared", args=[link.token])).status_code == 404

    expired = ReportShare.objects.create(
        report=report, created_by=customer, expires_at=timezone.now() - timedelta(minutes=1)
    )
    assert client.get(reverse("reports:shared", args=[expired.token])).status_code == 404
    assert client.get(reverse("reports:shared", args=["not-a-token"])).status_code == 404


def test_only_the_owner_can_share_or_revoke(client, customer, make_user):
    report = delivered(customer)
    link = ReportShare.objects.create(
        report=report, created_by=customer, expires_at=timezone.now() + timedelta(days=7)
    )
    client.force_login(make_user(email="other@example.com", role="customer"))
    assert share(client, report).status_code == 404
    response = client.post(reverse("reports:share_revoke", args=[report.order.public_id, link.pk]))
    assert response.status_code == 404
    link.refresh_from_db()
    assert link.revoked_at is None


def test_drafts_from_before_per_language_maps_still_open(client, customer):
    """Early drafts stored each static map as one file, not one per language."""
    from apps.reports.page import map_key

    assert map_key("analysis/run-1/location-boundary.svg", "fr").endswith("boundary.svg")
    assert map_key({"fr": "a-fr.svg", "en": "a-en.svg"}, "en") == "a-en.svg"
    assert map_key({"en": "a-en.svg"}, "fr") == "a-en.svg"
    report = delivered(customer)
    for version in report.versions.all():
        version.content["findings"][0]["maps"] = {"boundary": "analysis/old/location.svg"}
        version.save()
    client.force_login(customer)
    assert client.get(page_url(report)).status_code == 200
