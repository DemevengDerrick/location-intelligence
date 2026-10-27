"""Locate incidents from the place names an article mentions (FR-28, FR-29).

Names are matched against the gazetteer's names and aliases without regard to case or
accents. The most precise match wins; names the gazetteer does not know go to the
unmatched-places queue, where an analyst maps them (which adds an alias)."""

from django.db.models import F

from apps.gazetteer.models import GazetteerPlace, PlaceType

from .collectors import normalise
from .models import LocationPrecision, UnmatchedPlace

PRECISION = {
    PlaceType.LIEU_DIT: LocationPrecision.QUARTIER,
    PlaceType.VILLAGE: LocationPrecision.QUARTIER,
    PlaceType.QUARTIER: LocationPrecision.QUARTIER,
    PlaceType.COMMUNE: LocationPrecision.COMMUNE,
    PlaceType.ARRONDISSEMENT: LocationPrecision.COMMUNE,
    PlaceType.DEPARTMENT: LocationPrecision.DEPARTMENT,
    PlaceType.REGION: LocationPrecision.REGION,
}
# Most precise first
RANK = [
    PlaceType.LIEU_DIT,
    PlaceType.QUARTIER,
    PlaceType.VILLAGE,
    PlaceType.COMMUNE,
    PlaceType.ARRONDISSEMENT,
    PlaceType.DEPARTMENT,
    PlaceType.REGION,
]
ADMIN = {PlaceType.COMMUNE, PlaceType.DEPARTMENT, PlaceType.REGION}
IGNORED = {"cameroun", "cameroon", "republique du cameroun", "republic of cameroon"}


def names_of(place):
    return [place.name, *place.aliases]


def _index():
    index = {}
    for place in GazetteerPlace.objects.exclude(place_type=PlaceType.COUNTRY).only(
        "id", "name", "aliases", "place_type", "commune", "department", "region"
    ):
        for key in {normalise(name) for name in names_of(place)}:
            index.setdefault(key, []).append(place)
    return index


def match(names):
    """{name: [places]} for each name the gazetteer knows, most precise place first."""
    index = _index()
    found = {}
    for name in names:
        places = index.get(normalise(name))
        if places:
            found[name] = sorted(places, key=lambda p: RANK.index(p.place_type))
    return found


def locate(incident, source_item=None, fallback_place=None):
    """Set the incident's place, geometry and precision from its place names. Without a
    match, `fallback_place` (the place an area search was for) is used, if given."""
    names = [n for n in incident.place_names if normalise(n) not in IGNORED]
    found = match(names)
    for name in names:
        if name not in found:
            _record_unmatched(name, source_item)
    candidates = [_disambiguate(places, found, fallback_place) for places in found.values()]
    if not candidates and fallback_place is not None:
        candidates = [fallback_place]
    if not candidates:
        incident.place, incident.geometry, incident.precision = None, None, ""
        return incident
    place = min(candidates, key=lambda p: RANK.index(p.place_type))
    place = GazetteerPlace.objects.get(pk=place.pk)  # with its geometry
    incident.place = place
    incident.geometry = place.geometry
    incident.precision = PRECISION[place.place_type]
    return incident


def _disambiguate(places, found, fallback_place):
    """Many villages share a name: prefer the one inside an admin area the article (or the
    area search) also names; otherwise the most precise match."""
    context = {p.name for matches in found.values() for p in matches if p.place_type in ADMIN}
    if fallback_place is not None:
        context.add(fallback_place.name)
    inside = [p for p in places if context & {p.commune, p.department, p.region}]
    return (inside or places)[0]


def _record_unmatched(name, source_item):
    name = " ".join(name.split())[:200]
    if not name:
        return
    updated = UnmatchedPlace.objects.filter(name__iexact=name).update(
        occurrences=F("occurrences") + 1
    )
    if not updated:
        UnmatchedPlace.objects.create(name=name, example=source_item)


def resolve(unmatched):
    """The analyst mapped an unmatched name: add it as an alias and relocate the incidents
    that mention it."""
    from .models import Incident

    place = unmatched.resolved_place
    if place is None:
        return 0
    if normalise(unmatched.name) not in {normalise(n) for n in names_of(place)}:
        place.aliases = [*place.aliases, unmatched.name]
        place.save(update_fields=["aliases", "updated_at"])
    relocated = 0
    for incident in Incident.objects.filter(place_names__contains=[unmatched.name]):
        locate(incident)
        incident.save(update_fields=["place", "geometry", "precision", "updated_at"])
        relocated += 1
    return relocated
