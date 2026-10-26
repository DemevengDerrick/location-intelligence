"""Helpers for tests: a small active OSM import around a point."""

import math

from django.contrib.gis.geos import LineString, Point

from .models import Category, ImportStatus, OsmFeature, OsmImport


def offset(lon, lat, east_m, north_m):
    return (
        lon + east_m / (111_320 * math.cos(math.radians(lat))),
        lat + north_m / 110_574,
    )


def make_import(features=(), status=ImportStatus.ACTIVE, stamp="2026-10-20T00:00:00Z"):
    """features: (category, kind, name, paved, geometry) tuples."""
    osm_import = OsmImport.objects.create(source_url="test", data_timestamp=stamp, status=status)
    OsmFeature.objects.bulk_create(
        OsmFeature(
            osm_import=osm_import,
            category=category,
            kind=kind,
            name=name,
            paved=paved,
            osm_ref=f"t{i}",
            geom=geom,
        )  # fmt: skip
        for i, (category, kind, name, paved, geom) in enumerate(features)
    )
    return osm_import


def road(lon, lat, north_m, kind="residential", paved=None, name=""):
    """An east–west road `north_m` metres north (negative: south) of the point, 2 km long."""
    west = offset(lon, lat, -1000, north_m)
    east = offset(lon, lat, 1000, north_m)
    return (Category.ROAD, kind, name, paved, LineString([west, east], srid=4326))


def place(category, lon, lat, east_m, north_m, name="", kind=""):
    return (category, kind or str(category), name, None,
            Point(*offset(lon, lat, east_m, north_m), srid=4326))  # fmt: skip
