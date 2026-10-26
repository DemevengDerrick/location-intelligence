import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import translation

from apps.accounts import roles
from apps.orders.models import Attachment, AttachmentKind, IntakeDraft, Order, OrderStatus
from apps.parcels.models import Parcel
from apps.parcels.testing import DOUALA, square_m
from apps.pricing.models import ProductPrice

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("cameroon")]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\n"


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def step_url(draft, n):
    return reverse("intake:step", args=[draft.token, n])


def start(client, tier=""):
    response = client.post(reverse("intake:start"), {"tier": tier})
    assert response.status_code == 302
    return IntakeDraft.objects.latest("created_at")


def drawn(lon=DOUALA[0], lat=DOUALA[1], side=40):
    return json.dumps(json.loads(square_m(lon, lat, side)[0].geojson))


def complete_steps_1_to_3(client, draft):
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    client.post(
        step_url(draft, 2),
        {"stated_area": "2000", "stated_area_unit": "m2", "quartier": "Bonamoussadi"},
    )
    client.post(step_url(draft, 3), {"tier": "desk", "report_language": "en"})


def test_start_page_lists_what_to_prepare(client):
    response = client.get(reverse("intake:start"))
    assert response.status_code == 200
    assert "Have this ready" in response.content.decode()


def test_anonymous_customer_completes_an_order(client):
    draft = start(client, tier="desk")

    # Step 1: drawn boundary
    response = client.post(
        step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"}
    )
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.input_method == "drawn"
    assert draft.computed_area_m2 == pytest.approx(1600, rel=0.01)
    assert draft.commune == "Douala V"  # prefilled from the gazetteer
    assert draft.region == "Littoral"

    # Step 2: details with a photo
    response = client.post(
        step_url(draft, 2),
        {
            "stated_area": "0,2",
            "stated_area_unit": "ha",
            "quartier": "Bonamoussadi",
            "commune": "Douala V",
            "title_number": "TF 1234/W",
            "intended_use": "home",
            "documents": [SimpleUploadedFile("plot.png", PNG, content_type="image/png")],
        },
    )
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.stated_area_m2 == 2000
    assert draft.attachments.get().kind == AttachmentKind.PHOTO

    # Step 3: tier
    response = client.post(step_url(draft, 3), {"tier": "desk", "report_language": "en"})
    assert response.status_code == 302

    # Step 4: create the account during checkout
    response = client.post(
        step_url(draft, 4),
        {
            "email": "Ama@Example.com",
            "contact_name": "Ama Nkeng",
            "contact_phone": "+1 514 555 0100",
            "accept_terms": "on",
        },
    )
    assert response.status_code == 302
    user = get_user_model().objects.get(email="ama@example.com")
    assert not user.has_usable_password()  # signs in later with an emailed code
    assert user.groups.filter(name=roles.CUSTOMER).exists()
    assert user.first_name == "Ama"
    assert int(client.session["_auth_user_id"]) == user.pk

    # Step 5: review shows the area mismatch, then confirm
    review = client.get(step_url(draft, 5)).content.decode()
    assert "differs from the boundary by more than 10" in review
    response = client.post(step_url(draft, 5))
    order = Order.objects.get()
    assert response.url == reverse("payments:pay", args=[order.public_id])

    assert order.customer == user
    assert order.status == OrderStatus.SUBMITTED
    assert order.price_amount == Decimal("10000")
    assert order.currency == "XAF"
    assert order.language == "en"
    assert order.terms_version == "0.1"
    assert order.terms_accepted_at is not None
    parcel = Parcel.objects.get(order=order)
    assert parcel.computed_area_m2 == pytest.approx(1600, rel=0.01)
    assert parcel.stated_area_m2 == 2000
    assert parcel.title_number == "TF 1234/W"
    assert Attachment.objects.get().order == order

    # Submitting again (double click) doesn't create a second order.
    client.post(step_url(draft, 5))
    assert Order.objects.count() == 1


def test_pin_order_is_flagged_approximate(client):
    draft = start(client)
    pin = json.dumps({"type": "Point", "coordinates": list(DOUALA)})
    client.post(step_url(draft, 1), {"method": "pin", "geometry": pin, "crs": "wgs84"})
    draft.refresh_from_db()
    assert draft.is_approximate
    assert draft.pin.coords == pytest.approx(DOUALA)
    assert "approximate" in client.get(step_url(draft, 2)).content.decode()


def test_coordinates_file_upload(client):
    draft = start(client)
    ring = list(square_m(*DOUALA, 100)[0][0])[:-1]
    csv = "lat;lon\n" + "\n".join(f"{y};{x}" for x, y in ring)
    response = client.post(
        step_url(draft, 1),
        {
            "method": "file",
            "crs": "wgs84",
            "coords_file": SimpleUploadedFile("b.csv", csv.encode()),
        },
    )
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.input_method == "file"
    assert draft.computed_area_m2 == pytest.approx(10_000, rel=0.01)


def test_site_plan_only_order(client):
    draft = start(client)
    response = client.post(
        step_url(draft, 1),
        {
            "method": "site_plan",
            "crs": "wgs84",
            "site_plan": SimpleUploadedFile("plan.pdf", PDF, content_type="application/pdf"),
        },
    )
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.geometry is None
    assert draft.attachments.get().kind == AttachmentKind.SITE_PLAN


def test_location_errors_are_shown(client):
    draft = start(client)
    response = client.post(
        step_url(draft, 1), {"method": "drawn", "geometry": drawn(2.35, 48.85), "crs": "wgs84"}
    )
    assert response.status_code == 200
    assert "outside Cameroon" in response.content.decode()

    response = client.post(step_url(draft, 1), {"method": "drawn", "geometry": "", "crs": "wgs84"})
    assert "Draw the parcel boundary" in response.content.decode()


def test_documents_are_checked_by_content(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    fake = SimpleUploadedFile("photo.jpg", b"MZ\x90\x00 this is an exe", content_type="image/jpeg")
    response = client.post(step_url(draft, 2), {"stated_area_unit": "m2", "documents": [fake]})
    assert response.status_code == 200
    assert "not an accepted file type" in response.content.decode()
    assert not Attachment.objects.exists()


def test_steps_cannot_be_skipped(client):
    draft = start(client)
    response = client.get(step_url(draft, 4))
    assert response.url == step_url(draft, 1)


def test_other_browsers_cannot_open_a_draft(client):
    draft = start(client)
    assert Client().get(step_url(draft, 1)).status_code == 404


def test_draft_can_be_resumed_with_the_stored_token(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})

    other = Client()  # e.g. the session cookie was lost
    response = other.post(reverse("intake:resume"), {"token": str(draft.token)})
    assert response.url == step_url(draft, 2)
    assert other.get(step_url(draft, 2)).status_code == 200


def test_existing_email_must_sign_in(client, customer):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    response = client.post(
        step_url(draft, 4),
        {"email": customer.email, "contact_name": "X Y", "accept_terms": "on"},
    )
    assert response.status_code == 200
    assert "Sign in to continue" in response.content.decode()


def test_signed_in_customer_claims_the_draft_and_skips_account_creation(client, customer):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    client.force_login(customer)

    response = client.post(
        step_url(draft, 4), {"contact_name": "Kofi Mensah", "accept_terms": "on"}
    )
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.user == customer
    client.post(step_url(draft, 5))
    assert Order.objects.get().customer == customer


def test_terms_must_be_accepted(client):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    response = client.post(step_url(draft, 4), {"email": "a@example.com", "contact_name": "A B"})
    assert response.status_code == 200
    assert not get_user_model().objects.filter(email="a@example.com").exists()


def test_tier_follows_currency_and_rejects_missing_prices(client):
    client.cookies["currency"] = "EUR"
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    client.post(step_url(draft, 2), {"stated_area_unit": "m2"})
    ProductPrice.objects.filter(product__code="field", currency="EUR").delete()

    response = client.post(step_url(draft, 3), {"tier": "field", "report_language": "fr"})
    assert response.status_code == 200
    assert "not sold in EUR" in response.content.decode()

    response = client.post(step_url(draft, 3), {"tier": "desk", "report_language": "fr"})
    assert response.status_code == 302
    draft.refresh_from_db()
    assert draft.currency == "EUR"


def test_deadline_cannot_be_in_the_past(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    client.post(step_url(draft, 2), {"stated_area_unit": "m2"})
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    response = client.post(
        step_url(draft, 3), {"tier": "desk", "report_language": "fr", "deadline": yesterday}
    )
    assert "cannot be in the past" in response.content.decode()


def test_area_check_partial_flags_large_differences(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    url = reverse("intake:area_check", args=[draft.token])

    ok = client.post(url, {"stated_area": "1650", "stated_area_unit": "m2"}).content.decode()
    flagged = client.post(url, {"stated_area": "0.5", "stated_area_unit": "ha"}).content.decode()
    assert "differs from the boundary" not in ok
    assert "differs from the boundary" in flagged


def test_payment_page_is_private(client, customer, make_user):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    client.force_login(customer)
    client.post(step_url(draft, 4), {"contact_name": "K M", "accept_terms": "on"})
    client.post(step_url(draft, 5))
    order = Order.objects.get()

    intruder = Client()
    intruder.force_login(make_user("other@example.com", role=roles.CUSTOMER))
    assert intruder.get(reverse("payments:pay", args=[order.public_id])).status_code == 404
    assert client.get(reverse("payments:pay", args=[order.public_id])).status_code == 200


def test_submitted_draft_sends_the_customer_to_payment(client, customer):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    client.force_login(customer)
    client.post(step_url(draft, 4), {"contact_name": "K M", "accept_terms": "on"})
    client.post(step_url(draft, 5))
    order = Order.objects.get()

    # e.g. a double click or the browser's back button
    response = client.post(step_url(draft, 5))
    assert response.url == reverse("payments:pay", args=[order.public_id])
    assert Order.objects.count() == 1


def test_signed_out_owner_is_asked_to_sign_in(client, customer):
    draft = start(client)
    complete_steps_1_to_3(client, draft)
    client.force_login(customer)
    client.post(step_url(draft, 4), {"contact_name": "K M", "accept_terms": "on"})
    client.logout()

    response = client.get(step_url(draft, 5))
    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))
    assert "next=" in response.url


def test_pin_orders_do_not_show_a_misleading_area(client):
    draft = start(client)
    pin = json.dumps({"type": "Point", "coordinates": list(DOUALA)})
    client.post(step_url(draft, 1), {"method": "pin", "geometry": pin, "crs": "wgs84"})
    draft.refresh_from_db()
    assert draft.computed_area_m2 is None

    html = client.get(step_url(draft, 2)).content.decode()
    assert "cannot be measured" in html
    assert "Area of the boundary" not in html

    partial = client.post(
        reverse("intake:area_check", args=[draft.token]),
        {"stated_area": "5000", "stated_area_unit": "m2"},
    ).content.decode()
    assert "differs from the boundary" not in partial


@pytest.mark.django_db
def test_pin_parcel_has_no_computed_area(customer):
    order = Order.objects.create(customer=customer)
    parcel = Parcel.objects.create(
        order=order, geometry=square_m(*DOUALA, 50), input_method="pin", is_approximate=True
    )
    assert parcel.computed_area_m2 is None


def test_deadline_field_round_trips_in_both_languages(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    client.post(step_url(draft, 2), {"stated_area_unit": "m2"})
    deadline = (date.today() + timedelta(days=10)).isoformat()

    for language in ("fr", "en"):
        with translation.override(language):
            url = step_url(draft, 3)
            response = client.post(
                url, {"tier": "desk", "report_language": language, "deadline": deadline}
            )
            assert response.status_code == 302
            html = client.get(url).content.decode()
        # Re-rendered as ISO, the only format a browser date picker accepts.
        assert f'value="{deadline}"' in html
        assert f'max="{(date.today() + timedelta(days=730)).isoformat()}"' in html


def test_mistyped_deadline_explains_what_to_do(client):
    draft = start(client)
    client.post(step_url(draft, 1), {"method": "drawn", "geometry": drawn(), "crs": "wgs84"})
    client.post(step_url(draft, 2), {"stated_area_unit": "m2"})
    response = client.post(
        step_url(draft, 3), {"tier": "desk", "report_language": "fr", "deadline": "202611-02-01"}
    )
    assert "Choose the date in the calendar" in response.content.decode()
