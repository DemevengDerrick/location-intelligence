"""Load Cameroon's administrative boundaries from geoBoundaries (gbOpen) into the gazetteer.

ADM0 → country, ADM1 → regions, ADM2 → departments, ADM3 → communes. Re-running replaces
the previously loaded geoBoundaries places. Each level's licence and attribution is recorded
in the Dataset table, as the report's Sources section requires.
"""

import json

import httpx
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Dataset
from apps.gazetteer.models import GazetteerPlace, PlaceType

API = "https://www.geoboundaries.org/api/current/gbOpen/CMR/{level}/"
LEVELS = [
    ("ADM0", PlaceType.COUNTRY),
    ("ADM1", PlaceType.REGION),
    ("ADM2", PlaceType.DEPARTMENT),
    ("ADM3", PlaceType.COMMUNE),
]
SOURCE_PREFIX = "geoBoundaries gbOpen CMR"


class Command(BaseCommand):
    help = "Download Cameroon admin boundaries from geoBoundaries into the gazetteer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--simplified", action="store_true", help="Use the lighter simplified geometries."
        )

    def handle(self, *args, simplified=False, **options):
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            downloads = [
                (level, kind, *self._fetch(client, level, simplified)) for level, kind in LEVELS
            ]

        with transaction.atomic():
            GazetteerPlace.objects.filter(source__startswith=SOURCE_PREFIX).delete()
            for level, kind, meta, features in downloads:
                source = f"{SOURCE_PREFIX} {level} ({meta['buildDate']})"
                places = [
                    GazetteerPlace(
                        name=feature["properties"]["shapeName"],
                        place_type=kind,
                        geometry=_as_multipolygon(feature["geometry"]),
                        source=source,
                    )
                    for feature in features
                ]
                GazetteerPlace.objects.bulk_create(places)
                self._record_dataset(level, meta)
                self.stdout.write(f"{level}: {len(places)} {kind} places")
            self._fill_hierarchy()
        self.stdout.write(self.style.SUCCESS("Boundaries loaded."))

    def _fetch(self, client, level, simplified):
        meta = client.get(API.format(level=level)).raise_for_status().json()
        url = meta["simplifiedGeometryGeoJSON" if simplified else "gjDownloadURL"]
        return meta, client.get(url).raise_for_status().json()["features"]

    def _record_dataset(self, level, meta):
        Dataset.objects.update_or_create(
            slug=f"geoboundaries-cmr-{level.lower()}",
            defaults={
                "name": f"geoBoundaries Cameroon {level}",
                "provider": f"geoBoundaries (source: {meta.get('boundarySource', '')})",
                "version": meta.get("buildDate", ""),
                "licence": meta.get("boundaryLicense", ""),
                "attribution": (
                    "Runfola et al. (2020) geoBoundaries: A global database of political "
                    f"administrative boundaries. Source: {meta.get('boundarySource', '')}."
                ),
                "url": "https://www.geoboundaries.org/",
                "commercial_use_allowed": True,
            },
        )

    def _fill_hierarchy(self):
        """Write each place's parent region/department/commune names, by spatial containment."""
        parents = {
            kind: list(
                GazetteerPlace.objects.filter(place_type=kind, source__startswith=SOURCE_PREFIX)
            )
            for kind in (PlaceType.REGION, PlaceType.DEPARTMENT)
        }
        for place in GazetteerPlace.objects.filter(source__startswith=SOURCE_PREFIX).exclude(
            place_type=PlaceType.COUNTRY
        ):
            point = place.geometry.point_on_surface
            for kind, field in ((PlaceType.REGION, "region"), (PlaceType.DEPARTMENT, "department")):
                parent = next((p for p in parents[kind] if p.geometry.contains(point)), None)
                if parent:
                    setattr(place, field, parent.name)
            if place.place_type == PlaceType.COMMUNE:
                place.commune = place.arrondissement = place.name
            place.save(update_fields=["region", "department", "commune", "arrondissement"])


def _as_multipolygon(geojson_geometry):
    geom = GEOSGeometry(json.dumps(geojson_geometry), srid=4326)
    return geom if isinstance(geom, MultiPolygon) else MultiPolygon(geom, srid=4326)
