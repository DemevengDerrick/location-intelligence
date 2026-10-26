import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from apps.orders.models import Order
from apps.parcels.geometry import UTM_32N, UTM_33N, area_m2, utm_srid_for
from apps.parcels.models import InputMethod, Parcel


def square_m(lon, lat, side_m, srid):
    """A square of `side_m` metres built in UTM, returned in WGS84."""
    centre = Point(lon, lat, srid=4326).transform(srid, clone=True)
    x, y, h = centre.x, centre.y, side_m / 2
    ring = ((x - h, y - h), (x + h, y - h), (x + h, y + h), (x - h, y + h), (x - h, y - h))
    return MultiPolygon(Polygon(ring, srid=srid), srid=srid).transform(4326, clone=True)


@pytest.mark.parametrize(
    "lon, expected",
    [(9.70, UTM_32N), (11.52, UTM_32N), (13.40, UTM_33N)],  # Douala, Yaoundé, Garoua
)
def test_utm_zone_follows_longitude(lon, expected):
    assert utm_srid_for(Point(lon, 4.0, srid=4326)) == expected


def test_area_is_measured_in_square_metres():
    assert area_m2(square_m(9.70, 4.05, 100, UTM_32N)) == pytest.approx(10_000, rel=1e-3)


@pytest.mark.django_db
def test_parcel_stores_multipolygon_and_computes_area(customer):
    order = Order.objects.create(customer=customer)
    parcel = Parcel.objects.create(
        order=order,
        geometry=square_m(11.52, 3.87, 50, UTM_32N),
        input_method=InputMethod.DRAWN,
        stated_area_m2=2600,
    )

    parcel.refresh_from_db()
    assert parcel.geometry.srid == 4326
    assert parcel.geometry.geom_type == "MultiPolygon"
    assert parcel.computed_area_m2 == pytest.approx(2_500, rel=1e-3)
