import pytest
from django.contrib.auth.models import Group
from django.contrib.gis.geos import MultiPolygon
from django.core.cache import cache
from django.core.management import call_command
from django.urls import clear_url_caches
from django.utils.translation import trans_real

from apps.accounts import roles
from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.parcels.testing import CAMEROON_ROUGH, square_m


@pytest.fixture(scope="session", autouse=True)
def compiled_messages():
    """Templates are asserted in both languages, so the .mo files must be current."""
    call_command("compilemessages", ignore_patterns=[".venv"], verbosity=0)
    # Catalogues may already have been loaded (from the old .mo) during Django setup.
    trans_real._translations = {}
    trans_real._default = None
    clear_url_caches()


@pytest.fixture(autouse=True)
def clear_cache():
    """Rate-limit counters and cached settings must not leak between tests."""
    cache.clear()


@pytest.fixture
def make_user(django_user_model):
    def _make(email="user@example.com", password="pw-12345-secret", role=None, **extra):
        user = django_user_model.objects.create_user(email=email, password=password, **extra)
        if role:
            user.groups.add(Group.objects.get(name=role))
        return user

    return _make


@pytest.fixture
def customer(make_user):
    return make_user("customer@example.com", role=roles.CUSTOMER)


@pytest.fixture
def analyst(make_user):
    return make_user("analyst@example.com", role=roles.ANALYST)


@pytest.fixture
def cameroon(db):
    """Country outline plus one region and commune around Douala, for location checks."""
    GazetteerPlace.objects.create(
        name="Cameroun", place_type=PlaceType.COUNTRY, geometry=MultiPolygon(CAMEROON_ROUGH)
    )
    GazetteerPlace.objects.create(
        name="Littoral", place_type=PlaceType.REGION, geometry=square_m(9.70, 4.05, 60_000)
    )
    GazetteerPlace.objects.create(
        name="Douala V",
        place_type=PlaceType.COMMUNE,
        geometry=square_m(9.70, 4.05, 10_000),
        region="Littoral",
        commune="Douala V",
    )


@pytest.fixture(autouse=True)
def no_analysis_unless_marked(request, monkeypatch):
    """Paying starts the analysis, which calls external data services. Tests stay offline:
    only tests marked `run_analysis` (which fake the providers) run the pipeline."""
    if request.node.get_closest_marker("run_analysis") is None:
        monkeypatch.setattr(
            "apps.analysis.tasks.start_analysis.delay", lambda *args, **kwargs: None
        )
