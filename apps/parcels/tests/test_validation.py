import math

import pytest
from django.contrib.gis.geos import Point, Polygon
from django.utils import translation

from apps.core.models import SiteSetting
from apps.parcels.parsers import GeometryInputError
from apps.parcels.testing import DOUALA, square_m
from apps.parcels.validation import area_difference_pct, check_pin, check_polygon

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("cameroon")]


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def test_pin_becomes_an_approximate_30_m_circle():
    checked = check_pin(Point(*DOUALA, srid=4326))
    assert checked.is_approximate
    assert checked.geometry.geom_type == "MultiPolygon"
    assert checked.area_m2 == pytest.approx(math.pi * 30**2, rel=0.01)
    assert checked.warnings


def test_pin_buffer_radius_comes_from_settings():
    SiteSetting.objects.filter(key="parcel_intake").update(value={"pin_buffer_m": 50})
    SiteSetting.objects.get(key="parcel_intake").save()
    assert check_pin(Point(*DOUALA, srid=4326)).area_m2 == pytest.approx(math.pi * 50**2, rel=0.01)


@pytest.mark.parametrize("lon, lat", [(2.35, 48.85), (7.5, 9.0), (9.70, -4.05)])
def test_locations_outside_cameroon_are_rejected(lon, lat):
    with pytest.raises(GeometryInputError, match="outside Cameroon"):
        check_pin(Point(lon, lat, srid=4326))
    with pytest.raises(GeometryInputError, match="outside Cameroon"):
        check_polygon(square_m(lon, lat, 100))


def test_plausible_parcel_has_no_warnings():
    checked = check_polygon(square_m(*DOUALA, 30))
    assert checked.area_m2 == pytest.approx(900, rel=0.01)
    assert checked.warnings == []


def test_tiny_and_huge_parcels_warn_but_pass():
    tiny = check_polygon(square_m(*DOUALA, 5))
    huge = check_polygon(square_m(*DOUALA, 3_000))
    assert "very small" in tiny.warnings[0]
    assert "very large (900.0 ha)" in huge.warnings[0]


def test_size_warning_uses_french_number_format():
    with translation.override("fr"):
        huge = check_polygon(square_m(*DOUALA, 3_000))
    assert "900,0 ha" in huge.warnings[0]


def test_self_intersecting_boundary_is_repaired():
    x, y = DOUALA
    d = 0.0005
    bowtie = Polygon(((x, y), (x + d, y + d), (x + d, y), (x, y + d), (x, y)), srid=4326)
    assert not bowtie.valid
    checked = check_polygon(bowtie)
    assert checked.geometry.valid
    assert len(checked.geometry) == 2


def test_point_is_not_a_boundary():
    with pytest.raises(GeometryInputError, match="closed shape"):
        check_polygon(Point(*DOUALA, srid=4326))


@pytest.mark.parametrize(
    "computed, stated, expected",
    [(1000, 1100, 10.0), (1000, 800, -20.0), (1000, None, None), (None, 500, None)],
)
def test_area_difference(computed, stated, expected):
    assert area_difference_pct(computed, stated) == expected
