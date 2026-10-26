"""Spatial queries on the active OSM import."""

import math
from dataclasses import dataclass

from django.contrib.gis.geos import Polygon
from django.db import connection

from .models import OsmFeature


@dataclass
class Nearby:
    name: str
    kind: str
    distance_m: float  # from the parcel boundary (0 if touching or inside)
    lon: float  # closest point of the feature to the parcel centre
    lat: float
    paved: bool | None = None


def in_box(osm_import, category, west, south, east, north):
    box = Polygon.from_bbox((west, south, east, north))
    box.srid = 4326
    return OsmFeature.objects.filter(
        osm_import=osm_import, category=category, geom__bboverlaps=box
    ).only("geom", "name", "kind", "paved")


def nearest(osm_import, category, parcel, radius_m, limit=5, paved=None):
    """Up to `limit` features of a category within `radius_m` of the parcel, nearest first.

    The bounding-box test (&&) uses the spatial index; distances are then exact (geography).
    """
    lat = parcel.centroid.y
    pad_deg = radius_m / 110_574 / max(math.cos(math.radians(abs(lat) + 1)), 0.2)
    table = OsmFeature._meta.db_table
    sql = f"""
        WITH p AS (SELECT ST_GeomFromEWKB(%(parcel)s) AS g)
        SELECT f.name, f.kind, f.paved,
               ST_Distance(f.geom::geography, p.g::geography) AS d,
               ST_X(ST_ClosestPoint(f.geom, ST_Centroid(p.g))),
               ST_Y(ST_ClosestPoint(f.geom, ST_Centroid(p.g)))
        FROM {table} f, p
        WHERE f.osm_import_id = %(import_id)s AND f.category = %(category)s
          AND f.geom && ST_Expand(p.g, %(pad)s)
          {"AND f.paved = %(paved)s" if paved is not None else ""}
          AND ST_DWithin(f.geom::geography, p.g::geography, %(radius)s)
        ORDER BY d
        LIMIT %(limit)s
    """  # noqa: S608 (table name from the model; values are parameters)
    params = {
        "parcel": bytes(parcel.ewkb),
        "import_id": osm_import.pk,
        "category": str(category),
        "pad": pad_deg,
        "paved": paved,
        "radius": radius_m,
        "limit": limit,
    }
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return [
            Nearby(name, kind, float(d), float(x), float(y), is_paved)
            for name, kind, is_paved, d, x, y in cursor.fetchall()
        ]
