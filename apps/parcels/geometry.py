"""Geometry helpers shared by intake, the admin editor and the pipeline."""

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon

# Cameroon straddles two UTM zones; 12°E is the boundary between 32N and 33N.
UTM_32N = 32632
UTM_33N = 32633


def utm_srid_for(geom: GEOSGeometry) -> int:
    lon = geom.centroid.x
    return UTM_32N if lon < 12 else UTM_33N


def to_multipolygon(geom: GEOSGeometry) -> MultiPolygon:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon(geom, srid=geom.srid)
    raise ValueError(f"Expected a polygon, got {geom.geom_type}")


def area_m2(geom: GEOSGeometry) -> float:
    """Planar area in square metres, measured in the parcel's UTM zone."""
    projected = geom.transform(utm_srid_for(geom), clone=True)
    return projected.area
