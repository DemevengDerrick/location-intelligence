"""Load quartiers, villages and lieux-dits from the local OpenStreetMap extract into the
gazetteer (FR-28), so area signals can locate news about a neighbourhood and search the
parcel's own quartier first.

OSM maps most of them as points (place=suburb, quarter, neighbourhood, village, hamlet,
locality). Re-running replaces the places loaded before; aliases added by analysts on those
places are kept when the OSM node is the same.
"""

from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.gazetteer.models import GazetteerPlace, PlaceType

KINDS = {
    "suburb": PlaceType.QUARTIER,
    "quarter": PlaceType.QUARTIER,
    "neighbourhood": PlaceType.QUARTIER,
    "village": PlaceType.VILLAGE,
    "hamlet": PlaceType.VILLAGE,
    "locality": PlaceType.LIEU_DIT,
}
NAME_TAGS = ("name:fr", "alt_name", "official_name", "old_name", "name:en", "loc_name")
SOURCE_PREFIX = "OpenStreetMap place"


def read_places(path):
    """Yield (osm_ref, name, aliases, place_type, lon, lat) for named place nodes."""
    import osmium

    processor = osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(
        osmium.filter.KeyFilter("place")
    )
    for node in processor:
        tags = {tag.k: tag.v for tag in node.tags}
        kind = KINDS.get(tags.get("place"))
        name = tags.get("name", "").strip()
        if not kind or not name or not node.location.valid():
            continue
        aliases = []
        for key in NAME_TAGS:
            for value in tags.get(key, "").split(";"):
                value = value.strip()
                if value and value != name and value not in aliases:
                    aliases.append(value[:200])
        yield f"n{node.id}", name[:200], aliases, kind, node.location.lon, node.location.lat


class Command(BaseCommand):
    help = "Load OSM quartiers, villages and lieux-dits into the gazetteer."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(Path(settings.OSM_DATA_DIR) / "cameroon.osm.pbf"))

    def handle(self, *args, path, **options):
        previous = {
            p.source.rsplit(" ", 1)[-1]: p.aliases
            for p in GazetteerPlace.objects.filter(source__startswith=SOURCE_PREFIX)
        }
        places = []
        for ref, name, aliases, kind, lon, lat in read_places(path):
            kept = [a for a in previous.get(ref, []) if a not in aliases and a != name]
            places.append(
                GazetteerPlace(
                    name=name,
                    aliases=aliases + kept,
                    place_type=kind,
                    geometry=Point(lon, lat, srid=4326),
                    source=f"{SOURCE_PREFIX} {ref}",
                )
            )
        with transaction.atomic():
            GazetteerPlace.objects.filter(source__startswith=SOURCE_PREFIX).delete()
            GazetteerPlace.objects.bulk_create(places, batch_size=2000)
            self._fill_hierarchy()
        self.stdout.write(self.style.SUCCESS(f"{len(places)} places loaded."))

    def _fill_hierarchy(self):
        """Each place's commune, department and region names, by containment (one query per
        admin area rather than per place)."""
        for kind, field in (
            (PlaceType.REGION, "region"),
            (PlaceType.DEPARTMENT, "department"),
            (PlaceType.COMMUNE, "commune"),
        ):
            for area in GazetteerPlace.objects.filter(place_type=kind):
                GazetteerPlace.objects.filter(
                    source__startswith=SOURCE_PREFIX, geometry__within=area.geometry
                ).update(**{field: area.name})
