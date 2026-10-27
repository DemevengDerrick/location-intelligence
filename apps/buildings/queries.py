"""Spatial queries on the active building release."""

from django.contrib.gis.geos import Polygon

from .models import Building


def in_box(release, west, south, east, north, min_confidence=0):
    box = Polygon.from_bbox((west, south, east, north))
    box.srid = 4326
    return Building.objects.filter(
        release=release, geom__bboverlaps=box, confidence__gte=min_confidence
    ).only("geom", "confidence")
