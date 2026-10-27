"""Per-order news search that widens from the parcel's quartier up to its region (admin 1).

For each level, the place's saved searches (GDELT and the outlets' search feeds) are reused
while recent (SignalsSettings.max_age_days); otherwise they run again and are saved for the
next order in the same area. Widening stops at the first level with at least
SignalsSettings.min_items relevant items, and never goes past the region."""

import logging
from datetime import timedelta

import httpx
from django.db import transaction
from django.utils import timezone

from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.parcels.geometry import utm_srid_for

from . import collectors
from .config import signals_settings
from .geocode import names_of
from .models import AreaSearch, SearchProvider, Source, SourceType

logger = logging.getLogger(__name__)

LEVELS = [  # finest first; one place per level
    (PlaceType.QUARTIER, PlaceType.VILLAGE, PlaceType.LIEU_DIT),
    (PlaceType.COMMUNE, PlaceType.ARRONDISSEMENT),
    (PlaceType.DEPARTMENT,),
    (PlaceType.REGION,),
]


def hierarchy(point, quartier_m=1500):
    """One gazetteer place per level around the point, finest first: the nearest quartier or
    village within `quartier_m` (OSM maps most of them as points), or failing that the nearest
    lieu-dit (a junction or landmark, which the press names less often), then the commune,
    department and region containing the point."""
    chain = []
    srid = utm_srid_for(point)
    point_m = point.transform(srid, clone=True)
    near = GazetteerPlace.objects.filter(
        place_type__in=LEVELS[0], geometry__dwithin=(point, quartier_m / 100_000)
    )
    distances = [(point_m.distance(p.geometry.transform(srid, clone=True)), p) for p in near]
    distances = [(d, p) for d, p in distances if d <= quartier_m]
    settled = [(d, p) for d, p in distances if p.place_type != PlaceType.LIEU_DIT]
    if settled or distances:
        chain.append(min(settled or distances, key=lambda dp: dp[0])[1])
    containing = GazetteerPlace.objects.filter(
        geometry__intersects=point, place_type__in=[t for types in LEVELS[1:] for t in types]
    )
    for types in LEVELS[1:]:
        candidates = [p for p in containing if p.place_type in types]
        if candidates:
            chain.append(min(candidates, key=lambda p: p.geometry.area))
    return chain


def is_fresh(search, settings):
    return (
        search is not None
        and search.ok
        and search.searched_at is not None
        and search.searched_at >= timezone.now() - timedelta(days=settings.max_age_days)
    )


def _search_names(place):
    """Every name an article may use for the place (matching and the GDELT query)."""
    return [n for n in names_of(place) if len(n) >= 3]


def _outlet_terms(place):
    """Names typed into the outlets' search boxes: the place name, plus the city name for a
    department (news says "Douala", not "Wouri") and the French name for a region."""
    terms = [place.name]
    if place.place_type in (PlaceType.DEPARTMENT, PlaceType.REGION) and place.aliases:
        terms.append(place.aliases[0])
    return terms


def _run_gdelt(place, settings, http):
    query = collectors.gdelt_query(_search_names(place), settings.gdelt_keywords)
    entries = collectors.gdelt_search(
        query, settings.gdelt_timespan, settings.gdelt_max_records, http
    )
    return query, entries


def _run_outlets(place, settings, http):
    entries, queries, errors = [], [], []
    sources = Source.objects.filter(is_active=True).exclude(search_url="")
    terms = _outlet_terms(place)
    for source in sources:
        words = (
            settings.outlet_search_words_en
            if source.language == "en"
            else (settings.outlet_search_words)
        )
        for query in (f"{term} {word}" for word in words for term in terms):
            url = collectors.search_feed_url(source, query)
            queries.append(url)
            try:
                found = collectors.fetch_feed(url, http)
            except (httpx.HTTPError, ValueError, SyntaxError) as exc:  # one outlet down: go on
                errors.append(f"{source.name}: {exc!r}"[:300])
                continue
            entries += [(e, source) for e in found]
    if errors and not entries and len(errors) == len(queries):
        raise httpx.TransportError("; ".join(errors[:3]))
    return "\n".join(queries), entries


def run_search(place, provider, settings=None, http=None):
    """Search one place with one provider now and save the result."""
    settings = settings or signals_settings()
    http = http or collectors.client()
    names = _search_names(place)
    search, _ = AreaSearch.objects.get_or_create(place=place, provider=provider)
    try:
        if provider == SearchProvider.GDELT:
            query, found = _run_gdelt(place, settings, http)
            found = [(e, None) for e in found]
        else:
            query, found = _run_outlets(place, settings, http)
    except (httpx.HTTPError, ValueError) as exc:
        search.ok, search.error = False, repr(exc)[:1000]
        search.searched_at = timezone.now()
        search.save()
        raise
    with transaction.atomic():
        items = []
        for entry, source in found:
            # the place must be named, and the item must be about land
            text = f"{entry['title']} {entry.get('description', '')}"
            if not collectors.contains_any(text, names):
                continue
            if not collectors.relevant(entry, settings.keywords, settings.weak_keywords):
                continue
            items.append(collectors.store(entry, source or _gdelt_source())[0])
        search.query = query
        search.ok, search.error = True, ""
        search.searched_at = timezone.now()
        search.save()
        search.items.add(*items)
    return search


def _gdelt_source():
    source, _ = Source.objects.get_or_create(
        source_type=SourceType.NEWS_ALERT,
        url=collectors.GDELT_URL,
        defaults={"name": "GDELT", "language": "fr"},
    )
    return source


def ensure_search(place, provider, settings=None, http=None):
    """The place's saved search, run again first if missing or stale."""
    settings = settings or signals_settings()
    search = AreaSearch.objects.filter(place=place, provider=provider).first()
    if is_fresh(search, settings):
        return search, False
    return run_search(place, provider, settings, http), True


def widen(point, settings=None, http=None):
    """Search from the finest place up to the region. Returns a list of levels, finest
    first: {"place", "searches": [AreaSearch], "item_ids": set, "reused": bool}.

    A provider that fails (GDELT throttling, an outlet down) is skipped and its saved search
    marked failed, so the next order tries again; only if every search fails does this raise
    (the pipeline then retries the module)."""
    settings = settings or signals_settings()
    http = http or collectors.client()
    levels, total, failures, successes = [], set(), [], 0
    for place in hierarchy(point):
        searches, reused = [], True
        providers = [SearchProvider.OUTLETS]
        if settings.gdelt_enabled:
            providers.append(SearchProvider.GDELT)
        for provider in providers:
            try:
                search, ran = ensure_search(place, provider, settings, http)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Area search %s / %s failed: %r", place, provider, exc)
                failures.append(exc)
                continue
            successes += 1
            searches.append(search)
            reused = reused and not ran
        ids = {pk for s in searches for pk in s.items.values_list("pk", flat=True)}
        total |= ids
        levels.append({"place": place, "searches": searches, "item_ids": ids, "reused": reused})
        if len(total) >= settings.min_items:
            break
    if failures and not successes:
        raise failures[0]
    return levels
