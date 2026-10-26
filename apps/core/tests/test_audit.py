import pytest

from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


def test_login_is_audited(client, customer):
    client.login(email=customer.email, password="pw-12345-secret")

    entry = AuditLog.objects.get(action="auth.login")
    assert entry.actor == customer
    assert entry.target_id == str(customer.pk)


def test_failed_login_is_audited(client, customer):
    assert not client.login(email=customer.email, password="wrong")
    assert AuditLog.objects.filter(action="auth.login_failed", actor=None).exists()
