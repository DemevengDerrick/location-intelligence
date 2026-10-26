"""Administrative-boundary lookups backed by GazetteerPlace (loaded by `load_boundaries`)."""

import logging
from dataclasses import dataclass

from django.contrib.gis.geos import GEOSGeometry, Polygon

from .models import GazetteerPlace, PlaceType

logger = logging.getLogger(__name__)

# Used only until the real country outline is loaded: a generous bounding box.
CAMEROON_BBOX = Polygon.from_bbox((8.3, 1.6, 16.3, 13.2))
CAMEROON_BBOX.srid = 4326


def cameroon_outline() -> GEOSGeometry:
    place = GazetteerPlace.objects.filter(place_type=PlaceType.COUNTRY).only("geometry").first()
    if place is None:
        logger.warning("Cameroon outline not loaded; run `manage.py load_boundaries`.")
        return CAMEROON_BBOX
    return place.geometry


def is_in_cameroon(geom: GEOSGeometry) -> bool:
    return cameroon_outline().contains(geom.point_on_surface)


@dataclass(frozen=True)
class AdminUnits:
    region: str = ""
    department: str = ""
    commune: str = ""


def admin_units_at(geom: GEOSGeometry) -> AdminUnits:
    """Region, department and commune containing the geometry's interior point."""
    point = geom.point_on_surface
    names = dict(
        GazetteerPlace.objects.filter(
            place_type__in=[PlaceType.REGION, PlaceType.DEPARTMENT, PlaceType.COMMUNE],
            geometry__contains=point,
        ).values_list("place_type", "name")
    )
    return AdminUnits(
        region=names.get(PlaceType.REGION, ""),
        department=names.get(PlaceType.DEPARTMENT, ""),
        commune=names.get(PlaceType.COMMUNE, ""),
    )


def commune_at(geom: GEOSGeometry):
    """The commune (GazetteerPlace) containing the geometry's interior point, or None."""
    return GazetteerPlace.objects.filter(
        place_type=PlaceType.COMMUNE, geometry__contains=geom.point_on_surface
    ).first()
