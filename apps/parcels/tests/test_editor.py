"""Staff boundary editor and site-plan georeferencing (FR-38, FR-39, FR-40)."""

import io
import json

import pytest
from django.contrib.gis.geos import Point
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import translation
from PIL import Image

from apps.core.models import AuditLog
from apps.orders.models import Attachment, AttachmentKind, OrderStatus
from apps.orders.testing import make_order
from apps.parcels.geometry import utm_srid_for
from apps.parcels.georeference import fit_affine
from apps.parcels.models import InputMethod
from apps.parcels.parsers import GeometryInputError
from apps.parcels.plans import render_plan
from apps.parcels.testing import DOUALA, square_m

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr("apps.analysis.tasks.start_analysis.delay", calls.append)
    return calls


@pytest.fixture
def staff_client(client, make_user):
    analyst = make_user("analyst@example.com", role="analyst", is_staff=True)
    client.force_login(analyst)
    client.user = analyst
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = "en"
    return client


def editor_url(parcel):
    return reverse("admin:parcels_parcel_geometry", args=[parcel.pk])


def png(width=400, height=300):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


# --- georeferencing maths -------------------------------------------------------------------


def plan_points(pixels, scale_m=0.5, rotation_deg=20, noise_m=None):
    """Control points for a plan drawn at `scale_m` metres per pixel, rotated, near Douala."""
    import math

    centre = Point(*DOUALA, srid=4326)
    srid = utm_srid_for(centre)
    origin = centre.transform(srid, clone=True)
    angle = math.radians(rotation_deg)
    points = []
    for i, (px, py) in enumerate(pixels):
        x, y = px * scale_m, -py * scale_m  # pixel y grows downwards
        east = origin.x + x * math.cos(angle) - y * math.sin(angle)
        north = origin.y + x * math.sin(angle) + y * math.cos(angle)
        if noise_m and i == 0:
            east += noise_m
        lnglat = Point(east, north, srid=srid).transform(4326, clone=True)
        points.append({"pixel": [px, py], "lnglat": [lnglat.x, lnglat.y]})
    return points


def test_three_points_fit_a_plan_exactly():
    fit = fit_affine(plan_points([(0, 0), (400, 0), (0, 300)]), 400, 300)
    assert fit.rmse_m is None  # nothing left to check against
    assert max(fit.residuals_m) < 0.01
    top_left, top_right = Point(fit.corners[0], srid=4326), Point(fit.corners[1], srid=4326)
    srid = utm_srid_for(top_left)
    width_m = top_left.transform(srid, clone=True).distance(top_right.transform(srid, clone=True))
    assert width_m == pytest.approx(200, abs=0.05)  # 400 px at 0.5 m


def test_a_misplaced_point_shows_in_the_residuals():
    points = plan_points([(0, 0), (400, 0), (400, 300), (0, 300), (200, 150)], noise_m=6)
    fit = fit_affine(points, 400, 300)
    assert fit.rmse_m > 1
    assert fit.residuals_m[0] == max(fit.residuals_m)


@pytest.mark.parametrize(
    ("pixels", "message"),
    [
        ([(0, 0), (10, 10)], "at least 3"),
        ([(0, 0), (10, 10), (20, 20)], "on one line"),
    ],
)
def test_bad_control_points_are_explained(pixels, message):
    with pytest.raises(GeometryInputError, match=message):
        fit_affine(plan_points(pixels), 400, 300)


def test_plans_render_from_images_and_pdfs():
    data, width, height = render_plan(png(5000, 2500), "image/png", "plan.png")
    assert data.startswith(b"\x89PNG") and (width, height) == (2400, 1200)

    pdf = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(pdf, format="PDF")
    data, width, height = render_plan(pdf.getvalue(), "application/pdf", "plan.pdf")
    assert data.startswith(b"\x89PNG") and width > height

    with pytest.raises(GeometryInputError):
        render_plan(b"not an image", "image/jpeg", "plan.jpg")


# --- the editor -----------------------------------------------------------------------------


def test_editor_is_for_analysts_only(client, customer, make_user):
    parcel = make_order(customer).parcels.get()
    client.force_login(make_user("helper@example.com", is_staff=True))
    assert client.get(editor_url(parcel)).status_code == 403


def test_site_plan_order_is_georeferenced_and_starts_processing(
    staff_client, customer, cameroon, started, django_capture_on_commit_callbacks
):
    order = make_order(customer, geometry=False, status=OrderStatus.NEEDS_GEOREFERENCING)
    parcel = order.parcels.get()
    plan = Attachment.objects.create(
        order=order, kind=AttachmentKind.SITE_PLAN, content_type="image/png",
        original_name="plan.png", file=ContentFile(png(), name="plan.png"),
    )  # fmt: skip

    page = staff_client.get(editor_url(parcel))
    assert page.status_code == 200
    config = page.context["config"]
    assert config["geometry"] is None and config["plans"][0]["name"] == "plan.png"

    image = staff_client.get(config["plans"][0]["url"])
    assert image.status_code == 200 and image["Content-Type"] == "image/png"

    fit = staff_client.post(
        config["urls"]["georeference"],
        json.dumps({"attachment": plan.pk, "width": 400, "height": 300,
                    "points": plan_points([(0, 0), (400, 0), (400, 300), (0, 300)])}),
        content_type="application/json",
    )  # fmt: skip
    assert fit.status_code == 200 and len(fit.json()["corners"]) == 4
    plan.refresh_from_db()
    assert len(plan.georeference["points"]) == 4  # the analyst can come back to it

    with django_capture_on_commit_callbacks(execute=True):
        response = staff_client.post(
            editor_url(parcel), {"geometry": square_m(*DOUALA, 30).json, "note": "From plan"}
        )
    assert response.status_code == 302
    parcel.refresh_from_db()
    order.refresh_from_db()
    assert parcel.input_method == InputMethod.ANALYST
    assert parcel.computed_area_m2 == pytest.approx(900, rel=0.01)
    assert order.status == OrderStatus.PROCESSING
    assert started == [order.pk]
    assert not parcel.geometry_history.exists()  # there was no boundary before
    entry = AuditLog.objects.get(action="parcel.boundary_saved")
    assert entry.data["note"] == "From plan" and entry.actor == staff_client.user


def test_a_delivered_report_gets_a_new_boundary_and_a_fresh_analysis(
    staff_client, customer, cameroon, started, django_capture_on_commit_callbacks
):
    order = make_order(customer, status=OrderStatus.DELIVERED)
    parcel = order.parcels.get()
    old = parcel.geometry
    with django_capture_on_commit_callbacks(execute=True):
        staff_client.post(editor_url(parcel), {"geometry": square_m(*DOUALA, 50).json})
    order.refresh_from_db()
    assert order.status == OrderStatus.PROCESSING and started == [order.pk]
    history = parcel.geometry_history.get()
    assert history.geometry.equals_exact(old, 1e-9) and history.input_method == InputMethod.DRAWN


def test_pin_orders_lose_the_approximate_flag(staff_client, customer, cameroon, started):
    order = make_order(customer, status=OrderStatus.IN_REVIEW)
    parcel = order.parcels.get()
    parcel.is_approximate = True
    parcel.save()
    staff_client.post(editor_url(parcel), {"geometry": square_m(*DOUALA, 30).json})
    parcel.refresh_from_db()
    assert not parcel.is_approximate and parcel.computed_area_m2 > 0


def test_invalid_boundaries_and_closed_orders_are_refused(staff_client, customer, cameroon):
    order = make_order(customer, status=OrderStatus.IN_REVIEW)
    parcel = order.parcels.get()
    outside = square_m(2.35, 48.85, 30)  # Paris
    response = staff_client.post(editor_url(parcel), {"geometry": outside.json}, follow=True)
    assert "outside Cameroon" in response.content.decode()
    response = staff_client.post(editor_url(parcel), {"geometry": ""}, follow=True)
    assert "Draw the boundary" in response.content.decode()

    order.status = OrderStatus.REFUNDED
    order.save()
    response = staff_client.post(
        editor_url(parcel), {"geometry": square_m(*DOUALA, 30).json}, follow=True
    )
    assert "can no longer be changed" in response.content.decode()
    assert not parcel.geometry_history.exists()


def test_typed_coordinates_become_a_boundary(staff_client, customer):
    parcel = make_order(customer).parcels.get()
    url = reverse("admin:parcels_parcel_coordinates", args=[parcel.pk])
    text = "9.7000, 4.0500\n9.7004, 4.0500\n9.7004, 4.0504\n9.7000, 4.0504"
    response = staff_client.post(url, {"text": text, "crs": "wgs84"})
    assert response.status_code == 200
    assert response.json()["geometry"]["type"] == "Polygon"
    bad = staff_client.post(url, {"text": "9.7, 4.05", "crs": "wgs84"})
    assert bad.status_code == 400 and "3 corner" in bad.json()["error"]
