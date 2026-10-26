"""Geometry helpers shared by tests."""

from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from .geometry import utm_srid_for

# A rough outline of Cameroon (lon, lat), good enough for inside/outside tests.
CAMEROON_ROUGH = Polygon(
    (
        (8.5, 4.5), (9.0, 3.9), (9.8, 2.3), (11.3, 2.2), (13.3, 2.2), (15.0, 1.7),
        (16.2, 2.2), (15.5, 4.0), (14.6, 5.5), (14.6, 7.5), (15.5, 9.9), (14.9, 12.0),
        (14.5, 13.1), (13.6, 11.9), (13.3, 10.5), (12.0, 8.0), (10.7, 6.6), (9.7, 6.4),
        (8.8, 5.9), (8.5, 4.5),
    ),
    srid=4326,
)  # fmt: skip

DOUALA = (9.70, 4.05)
YAOUNDE = (11.52, 3.87)
GAROUA = (13.40, 9.30)


def square_m(lon, lat, side_m):
    """A square of `side_m` metres centred on (lon, lat), built in UTM, returned in WGS84."""
    centre = Point(lon, lat, srid=4326)
    srid = utm_srid_for(centre)
    projected = centre.transform(srid, clone=True)
    x, y, h = projected.x, projected.y, side_m / 2
    ring = ((x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h), (x - h, y - h))
    return MultiPolygon(Polygon(ring, srid=srid), srid=srid).transform(4326, clone=True)


def square_corners_utm(lon, lat, side_m):
    """The four corners of the same square, as UTM easting/northing pairs."""
    centre = Point(lon, lat, srid=4326).transform(utm_srid_for(Point(lon, lat)), clone=True)
    x, y, h = centre.x, centre.y, side_m / 2
    return [(x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h)]
