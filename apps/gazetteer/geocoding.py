"""Place-name search for the order form: our gazetteer first, then OSM Nominatim.

Nominatim's public usage policy: at most 1 request per second, an identifying User-Agent,
cache results, no search-as-you-type. All calls go through the server (never the browser).
Swap `NominatimGeocoder` for a self-hosted Nominatim or Photon by changing NOMINATIM_URL or
providing another `Geocoder`.
"""

import hashlib
import logging
import time
from dataclasses import asdict, dataclass
from typing import Protocol

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, CharField, F, Func, IntegerField, Q, Value, When

from .models import GazetteerPlace, PlaceType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeocodeResult:
    label: str
    lon: float
    lat: float
    bbox: tuple[float, float, float, float] | None  # west, south, east, north
    source: str  # "gazetteer" or "osm"


class Geocoder(Protocol):
    def search(self, query: str, language: str, limit: int) -> list[GeocodeResult]: ...


# Smaller, more specific places first.
_TYPE_RANK = [
    PlaceType.QUARTIER,
    PlaceType.LIEU_DIT,
    PlaceType.VILLAGE,
    PlaceType.COMMUNE,
    PlaceType.ARRONDISSEMENT,
    PlaceType.DEPARTMENT,
    PlaceType.REGION,
]


class GazetteerGeocoder:
    def search(self, query, language, limit):
        rank = Case(
            *(When(place_type=t, then=Value(i)) for i, t in enumerate(_TYPE_RANK)),
            default=Value(len(_TYPE_RANK)),
            output_field=IntegerField(),
        )
        aliases_text = Func(
            F("aliases"), Value(" | "), function="array_to_string", output_field=CharField()
        )
        places = (
            GazetteerPlace.objects.exclude(place_type=PlaceType.COUNTRY)
            .annotate(rank=rank, aliases_text=aliases_text)
            .filter(Q(name__icontains=query) | Q(aliases_text__icontains=query))
            .order_by("rank", "name")[:limit]
        )
        return [_place_result(place) for place in places]


def _place_result(place):
    parents = [p for p in (place.commune, place.department, place.region) if p and p != place.name]
    label = ", ".join([place.name, *parents])
    centre = place.geometry.point_on_surface
    return GeocodeResult(label, centre.x, centre.y, place.geometry.extent, "gazetteer")


class NominatimGeocoder:
    RATE_LOCK_KEY = "nominatim:lock"
    CACHE_TTL = 60 * 60 * 24 * 30

    def __init__(self, base_url=None, user_agent=None, client=None):
        self.base_url = (base_url or settings.NOMINATIM_URL).rstrip("/")
        self.user_agent = user_agent or settings.NOMINATIM_USER_AGENT
        self.client = client or httpx.Client(timeout=10)

    def search(self, query, language, limit):
        key = (
            "nominatim:"
            + hashlib.sha256(f"{language}|{limit}|{query.lower()}".encode()).hexdigest()
        )
        cached = cache.get(key)
        if cached is not None:
            return [GeocodeResult(**r) for r in cached]
        if not self._acquire_slot():
            logger.info("Nominatim busy; skipping search for %r", query)
            return []
        try:
            response = self.client.get(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "format": "jsonv2",
                    "countrycodes": "cm",
                    "limit": limit,
                    "accept-language": language,
                },
                headers={"User-Agent": self.user_agent},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Nominatim search failed")
            return []
        results = [_osm_result(item) for item in response.json()]
        cache.set(key, [asdict(r) for r in results], self.CACHE_TTL)
        return results

    def _acquire_slot(self, wait=2.0):
        """One request per second across all web processes, via a 1-second cache lock."""
        deadline = time.monotonic() + wait
        while not cache.add(self.RATE_LOCK_KEY, 1, timeout=1):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)
        return True


def _osm_result(item):
    south, north, west, east = (float(v) for v in item["boundingbox"])
    return GeocodeResult(
        item["display_name"],
        float(item["lon"]),
        float(item["lat"]),
        (west, south, east, north),
        "osm",
    )


class ChainGeocoder:
    """Ask each geocoder in turn until `limit` results are collected."""

    def __init__(self, *geocoders):
        self.geocoders = geocoders

    def search(self, query, language, limit):
        results = []
        for geocoder in self.geocoders:
            results += geocoder.search(query, language, limit - len(results))
            if len(results) >= limit:
                break
        return results


def default_geocoder() -> Geocoder:
    return ChainGeocoder(GazetteerGeocoder(), NominatimGeocoder())
