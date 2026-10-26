import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from rest_framework.views import APIView

from apps.accounts import roles
from apps.accounts.permissions import HasRole, has_role, role_required

pytestmark = pytest.mark.django_db


@role_required(roles.ANALYST)
def analyst_view(request):
    return HttpResponse("ok")


def _request(user):
    request = RequestFactory().get("/en/staff/")
    request.user = user
    return request


def test_role_required_allows_matching_role(analyst):
    assert analyst_view(_request(analyst)).status_code == 200


def test_role_required_denies_other_role(customer):
    with pytest.raises(PermissionDenied):
        analyst_view(_request(customer))


def test_role_required_sends_anonymous_users_to_login():
    response = analyst_view(_request(AnonymousUser()))
    assert response.status_code == 302
    assert "login" in response.url


def test_admin_role_holds_every_role(make_user):
    admin = make_user("admin@example.com", role=roles.ADMIN)
    assert has_role(admin, roles.ANALYST)
    assert has_role(admin, roles.PARTNER)


def test_drf_has_role_permission(analyst, customer):
    class AnalystOnly(APIView):
        required_roles = (roles.ANALYST,)

    permission = HasRole()
    assert permission.has_permission(_request(analyst), AnalystOnly())
    assert not permission.has_permission(_request(customer), AnalystOnly())
