"""Signing in, especially for accounts created at checkout without a password (FR-17)."""

import re

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import translation

pytestmark = pytest.mark.django_db

EMAIL = "awa@example.cm"


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


@pytest.fixture
def passwordless():
    """An account as checkout creates it when the password is left empty."""
    user = get_user_model().objects.create_user(email=EMAIL, password=None)
    user.set_unusable_password()
    user.save()
    EmailAddress.objects.create(user=user, email=EMAIL, primary=True, verified=False)
    return user


def code_from(message):
    return re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", message.body).group(1)  # e.g. DKWR-SSRF


def test_passwordless_account_signs_in_with_an_emailed_code(client, passwordless):
    response = client.post(reverse("account_request_login_code"), {"email": EMAIL})
    assert response.status_code == 302
    assert mail.outbox[-1].to == [EMAIL]
    response = client.post(response.url, {"code": code_from(mail.outbox[-1])})
    assert response.status_code == 302
    assert client.get(reverse("portal:orders")).status_code == 200


def test_passwordless_account_can_choose_a_password_by_reset(client, passwordless):
    client.post(reverse("account_reset_password"), {"email": EMAIL})
    assert mail.outbox and mail.outbox[-1].to == [EMAIL]


def test_sign_in_page_offers_both_ways_and_explains_codes(client):
    html = client.get(reverse("account_login")).content.decode()
    assert 'name="login"' in html and 'name="password"' in html
    assert "Email me a sign-in code" in html
    assert "left the password empty" in html
    assert reverse("account_request_login_code") in html
    assert "Continue with Google" not in html  # no credentials configured


def test_sign_in_page_is_in_french_too(client):
    with translation.override("fr"):
        html = client.get(reverse("account_login")).content.decode()
    assert "Se connecter" in html and "code" in html


def test_wrong_password_shows_an_error_on_the_page(client, make_user):
    make_user(email=EMAIL)
    response = client.post(reverse("account_login"), {"login": EMAIL, "password": "wrong"})
    assert response.status_code == 200
    assert 'role="alert"' in response.content.decode()


def test_passwordless_customer_is_offered_to_set_a_password(client, passwordless):
    client.force_login(passwordless)
    html = client.get(reverse("portal:account")).content.decode()
    assert "no password yet" in html and reverse("account_set_password") in html

    response = client.post(
        reverse("account_set_password"),
        {"password1": "Mbanga-River-2026", "password2": "Mbanga-River-2026"},
    )
    assert response.status_code == 302 and response.url == reverse("portal:account")
    passwordless.refresh_from_db()
    assert passwordless.has_usable_password()
    html = client.get(reverse("portal:account")).content.decode()
    assert reverse("account_change_password") in html

    client.logout()
    response = client.post(
        reverse("account_login"), {"login": EMAIL, "password": "Mbanga-River-2026"}
    )
    assert response.status_code == 302


@pytest.mark.parametrize(
    "name",
    ["account_signup", "account_request_login_code", "account_reset_password"],
)
def test_other_entrance_pages_use_the_site_styling(client, name):
    html = client.get(reverse(name)).content.decode()
    assert "rounded-lg border" in html  # the entrance card
    assert "bg-emerald-700" in html  # the primary button
    assert 'class="block font-medium"' in html  # visible field labels


def test_mailbox_hint_only_in_development(client, settings):
    settings.DEBUG = False
    assert "Mailpit" not in client.get(reverse("account_login")).content.decode()
    settings.DEBUG = True
    assert "Mailpit" in client.get(reverse("account_login")).content.decode()
