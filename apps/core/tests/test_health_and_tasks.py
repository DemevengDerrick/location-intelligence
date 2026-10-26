from types import SimpleNamespace

import pytest

from apps.core import views
from apps.core.tasks import ping

pytestmark = pytest.mark.django_db


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(views, "_check_redis", lambda: None)
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json() == {"db": "ok", "redis": "ok", "storage": "ok"}


def test_health_reports_failing_dependency(client, monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(views, "_check_redis", broken)
    response = client.get("/health/")
    assert response.status_code == 503
    assert response.json()["redis"] == "error"


def test_ping_task_runs():
    assert ping.delay().get(timeout=5) == "pong"


def test_health_fails_when_the_bucket_is_missing(client, monkeypatch):
    """exists() can't see a missing bucket, so the check must ask for the bucket itself."""

    def head_bucket(Bucket):
        raise RuntimeError("NoSuchBucket")

    client_ = SimpleNamespace(head_bucket=head_bucket)
    storage = SimpleNamespace(
        bucket_name="app-private", connection=SimpleNamespace(meta=SimpleNamespace(client=client_))
    )
    monkeypatch.setattr(views, "_check_redis", lambda: None)
    monkeypatch.setattr(views, "default_storage", storage)
    response = client.get("/health/")
    assert response.status_code == 503
    assert response.json()["storage"] == "error"
