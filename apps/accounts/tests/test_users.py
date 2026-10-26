import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts import roles

pytestmark = pytest.mark.django_db


def test_user_logs_in_with_email_and_has_locale_preferences(client, make_user):
    user = make_user("ama@example.com", password="pw-12345-secret", language="en", currency="CAD")

    assert get_user_model().USERNAME_FIELD == "email"
    assert user.language == "en"
    assert user.currency == "CAD"
    assert client.login(email="ama@example.com", password="pw-12345-secret")


def test_role_groups_exist_with_base_permissions():
    names = set(Group.objects.values_list("name", flat=True))
    assert set(roles.ALL_ROLES) <= names

    analyst = Group.objects.get(name=roles.ANALYST)
    assert analyst.permissions.filter(codename="change_order").exists()
    assert not analyst.permissions.filter(codename="change_payment").exists()
    assert Group.objects.get(name=roles.CUSTOMER).permissions.count() == 0


def test_signup_assigns_customer_role_and_language(client):
    response = client.post(
        "/en/accounts/signup/",
        {
            "email": "new@example.com",
            "password1": "Very-Long-pw-981",
            "password2": "Very-Long-pw-981",
        },
    )

    assert response.status_code == 302
    user = get_user_model().objects.get(email="new@example.com")
    assert user.groups.filter(name=roles.CUSTOMER).exists()
    assert user.language == "en"
