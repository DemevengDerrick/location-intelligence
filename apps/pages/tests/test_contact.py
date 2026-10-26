import pytest
from django.core import mail

from apps.pages.models import Lead

pytestmark = pytest.mark.django_db

VALID = {
    "name": "Ama Nkeng",
    "email": "ama@example.com",
    "phone": "+1 514 555 0100",
    "message": "I am looking at a plot in Bonamoussadi.",
    "consent": "on",
}


def test_lead_is_saved_and_staff_notified(client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post("/en/contact/", VALID)

    assert response.status_code == 302
    lead = Lead.objects.get()
    assert lead.email == "ama@example.com"
    assert lead.language == "en"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ops@example.com"]
    assert "Ama Nkeng" in mail.outbox[0].subject


def test_consent_is_required(client):
    response = client.post("/en/contact/", {**VALID, "consent": ""})
    assert response.status_code == 200
    assert not Lead.objects.exists()


def test_honeypot_submissions_are_dropped_silently(client):
    response = client.post("/en/contact/", {**VALID, "website": "http://spam.example"})
    assert response.status_code == 302
    assert not Lead.objects.exists()


def test_contact_form_is_rate_limited(client):
    for _ in range(5):
        client.post("/fr/contact/", VALID)
    response = client.post("/fr/contact/", VALID)

    assert response.status_code == 200
    assert Lead.objects.count() == 5
