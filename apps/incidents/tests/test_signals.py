"""Area signals (TRD §5): collection, geocoding, the widening area search, extraction and
analyst review. Everything stays offline (fake web, fake extractor)."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from django.contrib.gis.geos import Point
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.core import llm
from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.incidents import area_search, collectors, extraction, geocode, manual
from apps.incidents.config import SignalsSettings
from apps.incidents.models import (
    AreaSearch,
    Incident,
    IncidentSource,
    LocationPrecision,
    ReviewStatus,
    SearchProvider,
    Source,
    SourceItem,
    SourceType,
    UnmatchedPlace,
)
from apps.incidents.testing import FakeExtractor, Web, extracted, rss
from apps.parcels.testing import square_m

pytestmark = pytest.mark.django_db

WHEN = datetime(2025, 3, 15, 9, tzinfo=UTC)
PARCEL = Point(9.7, 4.05, srid=4326)


@pytest.fixture
def places(db):
    """Littoral ⊃ Wouri ⊃ Douala V, a Bonamoussadi quartier point 300 m from the parcel and
    a homonymous village far away."""
    region = GazetteerPlace.objects.create(
        name="Littoral", place_type=PlaceType.REGION, geometry=square_m(9.7, 4.05, 80_000)
    )
    department = GazetteerPlace.objects.create(
        name="Wouri",
        aliases=["Douala"],
        place_type=PlaceType.DEPARTMENT,
        geometry=square_m(9.7, 4.05, 30_000),
        region="Littoral",
    )
    commune = GazetteerPlace.objects.create(
        name="Douala V",
        aliases=["Douala 5e"],
        place_type=PlaceType.COMMUNE,
        geometry=square_m(9.7, 4.05, 10_000),
        region="Littoral",
        department="Wouri",
        commune="Douala V",
    )
    quartier = GazetteerPlace.objects.create(
        name="Bonamoussadi",
        place_type=PlaceType.QUARTIER,
        geometry=Point(9.7027, 4.05, srid=4326),
        region="Littoral",
        department="Wouri",
        commune="Douala V",
    )
    GazetteerPlace.objects.create(
        name="Bonamoussadi",
        place_type=PlaceType.QUARTIER,
        geometry=Point(11.5, 3.9, srid=4326),
        region="Centre",
        department="Mfoundi",
        commune="Yaoundé I",
    )
    return {"region": region, "department": department, "commune": commune, "quartier": quartier}


@pytest.fixture(autouse=True)
def no_gdelt_wait(monkeypatch):
    monkeypatch.setattr(collectors, "GDELT_INTERVAL_S", 0.01)


@pytest.fixture
def outlet(db):
    Source.objects.update(is_active=False)  # the seeded outlets stay out of these tests
    return Source.objects.create(
        name="Journal test",
        url="https://news.example.cm/feed/",
        search_url="https://news.example.cm/?s={query}&feed=rss2",
        source_type=SourceType.RSS,
        language="fr",
    )


# --- Collectors ---------------------------------------------------------------------------


def test_keywords_match_whole_words_without_accents():
    assert collectors.contains_any("Vague de DEGUERPISSEMENTS à Douala", ["déguerpissements"])
    assert collectors.contains_any("Un litige foncier à Bonamoussadi", ["litige foncier"])
    assert not collectors.contains_any("Une classe fermée", ["casse"])


def test_parse_rss_and_atom_feeds():
    entries = collectors.parse_feed(
        rss(("Casse à Makepè", "https://a.cm/1", "Des maisons <b>rasées</b>", WHEN))
    )
    assert entries == [
        {
            "url": "https://a.cm/1",
            "title": "Casse à Makepè",
            "description": "Des maisons rasées",
            "published_at": WHEN,
        }
    ]
    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Eviction in Limbe</title>'
        '<link href="https://b.cm/2"/><updated>2025-03-15T09:00:00Z</updated>'
        "<summary>Residents evicted</summary></entry></feed>"
    )
    assert collectors.parse_feed(atom)[0]["url"] == "https://b.cm/2"


def test_feeds_refuse_entity_expansion():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel>&a;</channel></rss>'
    with pytest.raises(ValueError):  # defusedxml's EntitiesForbidden
        collectors.parse_feed(bomb)


def test_feed_with_a_repeated_attribute_is_repaired():
    feed = rss(("Casse à Makepè", "https://a.cm/1", "x", WHEN)).replace(
        '<rss version="2.0">',
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" '
        'xmlns:media="http://search.yahoo.com/mrss/">',
    )
    assert [e["title"] for e in collectors.parse_feed(feed)] == ["Casse à Makepè"]


def test_land_words_in_passing_do_not_make_an_item_relevant():
    settings = SignalsSettings()

    def relevant(title, description=""):
        entry = {"title": title, "description": description}
        return collectors.relevant(entry, settings.keywords, settings.weak_keywords)

    assert relevant("Des habitants de Ngousso appelés à déguerpir")  # strong, in the title
    assert relevant("Le préfet installé", "Il devra régler les litiges fonciers du Wouri")
    assert relevant("Réforme foncière : le ministère passe à l'action")  # weak, in the title
    assert relevant("Tensions à Bali", "La chefferie conteste un lotissement")  # two weak
    assert not relevant("Un hôtel de 220 milliards", "fonds propres et foncier apportés")
    assert not relevant("Plantain", "valorisation du foncier et des fonciers des universités")


def test_duplicates_are_spotted_without_tracking_parameters():
    feed = "https://a.cm/article/?utm_source=rss&utm_medium=rss&p=12"
    assert collectors.content_hash(feed) == collectors.content_hash("https://A.cm/article/?p=12")
    assert collectors.content_hash(feed) != collectors.content_hash("https://a.cm/article/?p=13")


def test_refilter_removes_only_collected_off_topic_items(places, outlet):
    def item(n, title, description="", source=outlet):
        text = f"{title}\n\n{description}" if description else title
        return SourceItem.objects.create(
            url=f"https://a.cm/{n}",
            title=title,
            private_text=text,
            content_hash=f"h{n}",
            source=source,
        )

    off = item(1, "Un hôtel de 220 milliards", "fonds propres et foncier apportés")
    item(2, "Réforme foncière : le ministère passe à l'action")
    item(3, "Tensions à Bali", "La chefferie conteste un lotissement")
    item(4, "Article ajouté à la main", source=manual._manual_source())
    used = item(5, "Un marché rénové")
    IncidentSource.objects.create(incident=make_incident(places["quartier"]), source_item=used)

    call_command("refilter_items")
    assert SourceItem.objects.count() == 5  # listing only

    call_command("refilter_items", delete=True)
    assert not SourceItem.objects.filter(pk=off.pk).exists()
    assert SourceItem.objects.count() == 4


def test_robots_txt_is_respected():
    web = Web({"robots.txt": "User-agent: *\nDisallow: /\n"})
    assert collectors.fetch_feed("https://closed.example.cm/feed/", web.client()) == []
    assert web.requested == ["https://closed.example.cm/robots.txt"]


def test_items_are_deduplicated_by_url(outlet):
    entry = {"url": "https://a.cm/1", "title": "Casse", "description": "x", "published_at": WHEN}
    first, created = collectors.store(entry, outlet)
    second, created_again = collectors.store({**entry, "url": "HTTPS://A.CM/1#top"}, outlet)
    assert created and not created_again and first == second


def test_daily_collection_keeps_land_items_only(outlet, monkeypatch):
    from apps.incidents import tasks

    web = Web(
        {
            "news.example.cm/feed/": rss(
                ("Déguerpissement à Bonabéri", "https://news.example.cm/a", "", WHEN),
                ("Match de football", "https://news.example.cm/b", "", WHEN),
            ),
            "api.gdeltproject.org": {"articles": []},
        }
    )
    monkeypatch.setattr(collectors, "client", web.client)
    result = tasks.collect_sources()
    assert result["Journal test"] == 1
    assert "GDELT" not in result and not any("gdelt" in url for url in web.requested)
    assert list(SourceItem.objects.values_list("title", flat=True)) == [
        "Déguerpissement à Bonabéri"
    ]


def test_gdelt_query_and_cooldown(settings):
    query = collectors.gdelt_query(["Douala V", "Douala 5e"], ["foncier", "double vente"])
    assert query == '("Douala 5e" OR "Douala V") (foncier OR "double vente")'
    web = Web({"api.gdeltproject.org": 429})
    with pytest.raises(collectors.GdeltBusy):
        collectors.gdelt_search(query, http=web.client())
    with pytest.raises(collectors.GdeltBusy):  # cooling down: no second request
        collectors.gdelt_search(query, http=web.client())
    assert len(web.requested) == 1


# --- Geocoding ----------------------------------------------------------------------------


def test_geocode_prefers_the_homonym_in_the_named_commune(places):
    incident = Incident(incident_type="demolition", place_names=["Bonamoussadi", "Douala 5e"])
    geocode.locate(incident)
    assert incident.place == places["quartier"]
    assert incident.precision == LocationPrecision.QUARTIER


def test_unknown_names_go_to_the_queue_and_resolving_adds_an_alias(places):
    item = SourceItem.objects.create(url="https://a.cm/1", title="t", content_hash="h1")
    incident = Incident(incident_type="other", place_names=["Carrefour Kotto", "Cameroun"])
    geocode.locate(incident, item)
    incident.save()
    assert incident.place is None
    unmatched = UnmatchedPlace.objects.get()
    assert (unmatched.name, unmatched.example) == ("Carrefour Kotto", item)  # not "Cameroun"
    unmatched.resolved_place = places["commune"]
    unmatched.save()
    assert geocode.resolve(unmatched) == 1
    incident.refresh_from_db()
    assert incident.place == places["commune"]
    assert "Carrefour Kotto" in GazetteerPlace.objects.get(pk=places["commune"].pk).aliases


# --- Widening area search -----------------------------------------------------------------


def outlet_answer(titles_by_place):
    """Outlet search feed answering per place word in the query."""

    def answer(request):
        query = request.url.params.get("s", "")
        items = [
            (title, f"https://news.example.cm/{abs(hash(title))}", "", WHEN)
            for place, titles in titles_by_place.items()
            if query.startswith(place)
            for title in titles
        ]
        return httpx.Response(200, text=rss(*items))

    return answer


def test_hierarchy_goes_from_the_quartier_to_the_region(places):
    chain = area_search.hierarchy(PARCEL)
    assert [p.name for p in chain] == ["Bonamoussadi", "Douala V", "Wouri", "Littoral"]


def test_search_widens_until_enough_items_and_saves_each_place(places, outlet):
    web = Web(
        {
            "news.example.cm/?s=": outlet_answer(
                {
                    "Bonamoussadi": ["Litige foncier à Bonamoussadi"],
                    "Douala V": ["Casse à Douala 5e", "Le maire de Douala V inaugure un marché"],
                    "Wouri": ["Expropriation dans le Wouri", "Déguerpissement à Douala"],
                }
            ),
            "api.gdeltproject.org": {"articles": []},
        }
    )
    settings = SignalsSettings(min_items=3, outlet_search_words=["foncier"], gdelt_enabled=True)
    levels = area_search.widen(PARCEL, settings, web.client())
    assert [lv["place"].name for lv in levels] == ["Bonamoussadi", "Douala V", "Wouri"]
    assert [len(lv["item_ids"]) for lv in levels] == [1, 1, 2]  # the market story is not land
    assert AreaSearch.objects.filter(ok=True).count() == 6  # 3 places × (outlets, GDELT)

    # A second order in the same area reuses the saved searches: no request at all
    web.requested.clear()
    again = area_search.widen(PARCEL, settings, web.client())
    assert web.requested == []
    assert all(lv["reused"] for lv in again)


def test_stale_searches_run_again(places, outlet):
    web = Web({"api.gdeltproject.org": {"articles": []}})
    settings = SignalsSettings(min_items=1, max_age_days=30, outlet_search_words=["foncier"])
    area_search.widen(PARCEL, settings, web.client())
    AreaSearch.objects.update(searched_at=timezone.now() - timedelta(days=31))
    web.requested.clear()
    area_search.widen(PARCEL, settings, web.client())
    assert any("news.example.cm/?s=Bonamoussadi" in url for url in web.requested)


def test_gdelt_failure_does_not_stop_the_search(places, outlet):
    web = Web({"api.gdeltproject.org": 503})
    settings = SignalsSettings(min_items=1, outlet_search_words=["foncier"], gdelt_enabled=True)
    levels = area_search.widen(PARCEL, settings, web.client())
    assert len(levels) == 4  # nothing found, so up to the region
    failed = AreaSearch.objects.filter(provider=SearchProvider.GDELT, ok=False)
    assert failed.count() == 4  # tried again by the next order


def test_search_starts_at_a_quartier_rather_than_a_closer_landmark(places):
    GazetteerPlace.objects.create(
        name="Carrefour Lycée",
        place_type=PlaceType.LIEU_DIT,
        geometry=Point(9.7005, 4.05, srid=4326),
    )
    assert area_search.hierarchy(PARCEL)[0] == places["quartier"]


def test_english_outlets_are_searched_with_english_words(places, outlet):
    outlet.language = "en"
    outlet.save()
    web = Web({"api.gdeltproject.org": {"articles": []}})
    area_search.widen(PARCEL, SignalsSettings(min_items=1), web.client())
    searched = [url for url in web.requested if "news.example.cm/?s=" in url]
    assert "https://news.example.cm/?s=Bonamoussadi+land&feed=rss2" in searched
    assert not any("foncier" in url for url in searched)


def test_gdelt_is_off_by_default(places, outlet):
    web = Web()
    area_search.widen(PARCEL, SignalsSettings(min_items=1), web.client())
    assert not any("gdeltproject" in url for url in web.requested)
    assert not AreaSearch.objects.filter(provider=SearchProvider.GDELT).exists()


def test_search_fails_only_if_every_provider_fails(places, outlet):
    web = Web({"api.gdeltproject.org": 503, "news.example.cm/?s=": 503})
    with pytest.raises(httpx.HTTPError):
        settings = SignalsSettings(outlet_search_words=["foncier"], gdelt_enabled=True)
        area_search.widen(PARCEL, settings, web.client())


# --- Extraction ---------------------------------------------------------------------------


def test_extraction_creates_located_unreviewed_incidents(places):
    item = SourceItem.objects.create(
        url="https://a.cm/1", title="Casse", content_hash="h1", published_at=WHEN
    )
    long_summary = " ".join(["mot"] * 60)
    fake = FakeExtractor([extracted(summary_fr=long_summary), extracted(event_date="2024")])
    first, second = extraction.extract_item(item, fake)
    assert first.review_status == ReviewStatus.UNREVIEWED
    assert first.place == places["quartier"] and first.precision == LocationPrecision.QUARTIER
    assert len(first.summary_fr.split()) == 41  # 40 words and an ellipsis (FR-26)
    assert str(second.event_date) == "2024-01-01"
    assert IncidentSource.objects.filter(source_item=item).count() == 2
    item.refresh_from_db()
    assert item.extracted_at is not None


def test_extraction_records_a_refusal(places):
    item = SourceItem.objects.create(url="https://a.cm/1", title="t", content_hash="h1")
    assert extraction.extract_item(item, FakeExtractor(error=llm.LlmRefused("no"))) == []
    item.refresh_from_db()
    assert item.extraction_error.startswith("Refused")


def test_no_llm_call_without_a_key(settings):
    settings.ANTHROPIC_API_KEY = ""
    assert extraction.extractor() is None
    with pytest.raises(llm.LlmUnavailable):
        llm.parse(system="s", prompt="p", schema=extraction.Extraction)


# --- Review (admin) -----------------------------------------------------------------------


@pytest.fixture
def staff_client(client, make_user):
    user = make_user("analyst@example.com", role="analyst", is_staff=True, is_superuser=True)
    client.force_login(user)
    return client


def make_incident(place, **extra):
    return Incident.objects.create(
        incident_type="demolition",
        summary_fr="Démolitions selon la commune.",
        summary_en="Demolitions, according to the council.",
        place=place,
        geometry=place.geometry,
        precision=LocationPrecision.QUARTIER,
        **extra,
    )


def test_approval_requires_the_private_names_check(places, staff_client):
    incident = make_incident(places["quartier"])
    url = reverse("admin:incidents_incident_changelist")
    data = {"action": "approve", "_selected_action": [incident.pk]}
    response = staff_client.post(url, data)
    assert "no_private_names" in response.content.decode()  # the confirmation checkbox
    incident.refresh_from_db()
    assert incident.review_status == ReviewStatus.UNREVIEWED

    staff_client.post(url, {**data, "confirm": "1", "no_private_names": "on"})
    incident.refresh_from_db()
    assert incident.review_status == ReviewStatus.APPROVED and incident.reviewed_by


def test_merge_keeps_the_oldest_with_all_sources(places, staff_client):
    first, second = make_incident(places["quartier"]), make_incident(places["quartier"])
    for n, incident in enumerate((first, second)):
        item = SourceItem.objects.create(url=f"https://a.cm/{n}", title="t", content_hash=f"h{n}")
        IncidentSource.objects.create(incident=incident, source_item=item)
    staff_client.post(
        reverse("admin:incidents_incident_changelist"),
        {"action": "merge", "_selected_action": [first.pk, second.pk]},
    )
    second.refresh_from_db()
    assert second.review_status == ReviewStatus.MERGED and second.merged_into == first
    assert first.sources.count() == 2


def test_incident_map_lists_filtered_incidents(places, staff_client):
    make_incident(places["quartier"], review_status=ReviewStatus.APPROVED)
    make_incident(places["commune"])
    assert staff_client.get(reverse("admin:incidents_incident_map")).status_code == 200
    data = staff_client.get(
        reverse("admin:incidents_incident_map_data"), {"status": "approved"}
    ).json()
    assert len(data["features"]) == 1


def test_admin_location_map_uses_our_basemap(places, staff_client, settings):
    """The OSM tile servers refuse Django's default admin map: it draws on our basemap."""
    settings.BASEMAP_TILE_URL = "https://tiles.example.com/{z}/{y}/{x}"
    incident = make_incident(places["quartier"])
    page = staff_client.get(reverse("admin:incidents_incident_change", args=[incident.pk]))
    html = page.content.decode()
    assert 'url: "https://tiles.example.com/{z}/{y}/{x}"' in html
    assert "ol.source.OSM()" not in html


def test_add_item_from_a_pdf_notice(db, monkeypatch):
    monkeypatch.setattr(
        manual, "pdf_text", lambda data: "Arrêté portant déclaration d'utilité publique"
    )
    pdf = SimpleUploadedFile("dup.pdf", b"%PDF-1.4 ...", content_type="application/pdf")
    item, created = manual.add_item(pdf=pdf, outlet="MINDCAF")
    assert created and item.title == "dup.pdf" and "utilité publique" in item.private_text
    assert item.source.source_type == SourceType.MANUAL


def test_add_item_refuses_pages_robots_forbid(db, monkeypatch):
    web = Web({"robots.txt": "User-agent: *\nDisallow: /\n"})
    monkeypatch.setattr(collectors, "client", web.client)
    monkeypatch.setattr(manual, "public_address", lambda url: True)
    with pytest.raises(manual.ManualItemError) as error:
        manual.add_item(url="https://closed.example.cm/article")
    assert "robots.txt" in str(error.value)


def test_add_item_refuses_internal_addresses(db):
    for url in ("http://localhost:8000/admin/", "http://127.0.0.1/", "http://10.0.0.5/x"):
        with pytest.raises(manual.ManualItemError):
            manual.add_item(url=url)
