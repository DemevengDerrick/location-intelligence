import httpx
import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.gazetteer.geocoding import (
    ChainGeocoder,
    GazetteerGeocoder,
    NominatimGeocoder,
)
from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.parcels.testing import square_m

pytestmark = pytest.mark.django_db

NOMINATIM_REPLY = [
    {
        "display_name": "Bonamoussadi, Douala V, Wouri, Littoral, Cameroun",
        "lon": "9.7412",
        "lat": "4.0901",
        "boundingbox": ["4.07", "4.11", "9.72", "9.76"],
    }
]


def fake_nominatim(calls):
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=NOMINATIM_REPLY)

    return NominatimGeocoder(
        base_url="https://nominatim.test",
        user_agent="tests (ops@example.com)",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def places():
    GazetteerPlace.objects.create(
        name="Douala V",
        place_type=PlaceType.COMMUNE,
        geometry=square_m(9.74, 4.08, 8000),
        region="Littoral",
    )
    GazetteerPlace.objects.create(
        name="Bonamoussadi", place_type=PlaceType.QUARTIER, geometry=square_m(9.74, 4.09, 1500),
        aliases=["Bonamoussadi Carrefour", "Bona-Moussadi"], commune="Douala V", region="Littoral",
    )  # fmt: skip


def test_gazetteer_matches_names_and_aliases_smallest_place_first(places):
    results = GazetteerGeocoder().search("douala", "fr", 5)
    assert [r.label for r in results] == ["Douala V, Littoral"]

    results = GazetteerGeocoder().search("bona-mou", "fr", 5)
    assert results[0].label == "Bonamoussadi, Douala V, Littoral"
    assert results[0].source == "gazetteer"
    assert len(results[0].bbox) == 4


def test_nominatim_request_follows_usage_policy():
    calls = []
    results = fake_nominatim(calls).search("Bonamoussadi", "en", 5)

    request = calls[0]
    assert request.headers["User-Agent"] == "tests (ops@example.com)"
    assert request.url.params["countrycodes"] == "cm"
    assert request.url.params["accept-language"] == "en"
    assert results[0].lon == pytest.approx(9.7412)
    assert results[0].bbox == (9.72, 4.07, 9.76, 4.11)
    assert results[0].source == "osm"


def test_nominatim_results_are_cached():
    calls = []
    geocoder = fake_nominatim(calls)
    geocoder.search("Bonamoussadi", "fr", 5)
    cache.delete(NominatimGeocoder.RATE_LOCK_KEY)
    geocoder.search("BONAMOUSSADI", "fr", 5)
    assert len(calls) == 1


def test_nominatim_is_skipped_while_the_rate_slot_is_taken():
    calls = []
    cache.add(NominatimGeocoder.RATE_LOCK_KEY, 1, timeout=60)
    geocoder = fake_nominatim(calls)
    assert geocoder._acquire_slot(wait=0) is False
    assert geocoder.search("Akwa", "fr", 5) == []
    assert calls == []


def test_nominatim_errors_return_no_results():
    geocoder = NominatimGeocoder(
        base_url="https://nominatim.test",
        user_agent="tests",
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )
    assert geocoder.search("Akwa", "fr", 5) == []


def test_chain_asks_nominatim_only_when_the_gazetteer_is_short(places):
    calls = []
    chain = ChainGeocoder(GazetteerGeocoder(), fake_nominatim(calls))

    assert len(chain.search("Bonamoussadi", "fr", 1)) == 1
    assert calls == []

    results = chain.search("Bonamoussadi", "fr", 5)
    assert [r.source for r in results] == ["gazetteer", "osm"]


def test_search_endpoint(client, places, monkeypatch):
    monkeypatch.setattr(
        "apps.orders.intake_views.default_geocoder", lambda: ChainGeocoder(GazetteerGeocoder())
    )
    url = reverse("intake:search")
    assert client.get(url, {"q": "bo"}).json() == {"results": []}
    results = client.get(url, {"q": "bonamoussadi"}).json()["results"]
    assert results[0]["label"].startswith("Bonamoussadi")
