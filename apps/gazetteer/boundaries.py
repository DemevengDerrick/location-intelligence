"""Administrative-boundary lookups backed by GazetteerPlace (loaded by `load_boundaries`)."""

import json
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


BOUNDARY_LEVELS = {  # place type: simplification tolerance in degrees (~1.5 km, 800 m, 400 m)
    PlaceType.REGION: 0.015,
    PlaceType.DEPARTMENT: 0.008,
    PlaceType.COMMUNE: 0.004,
}


def _rounded(geom, digits=4):
    """GeoJSON geometry with coordinates rounded (4 decimals ≈ 10 m): a third of the size."""

    def walk(value):
        if isinstance(value, float):
            return round(value, digits)
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    data = json.loads(geom.geojson)
    data["coordinates"] = walk(data["coordinates"])
    return data


def boundaries_geojson():
    """Simplified region, department and commune outlines, the country outline and a mask
    covering the rest of the world, for the order form's map (cached: they rarely change)."""
    from django.core.cache import cache

    key = "boundaries-geojson-v2"
    cached = cache.get(key)
    if cached is not None:
        return cached
    features = []
    for place_type, tolerance in BOUNDARY_LEVELS.items():
        for place in GazetteerPlace.objects.filter(place_type=place_type).only("name", "geometry"):
            shape = place.geometry.simplify(tolerance, preserve_topology=True)
            features.append(
                {
                    "type": "Feature",
                    "properties": {"level": str(place_type), "name": place.name},
                    "geometry": _rounded(shape),
                }
            )
    country = cameroon_outline().simplify(0.005, preserve_topology=True)
    world = Polygon.from_bbox((-180, -85, 180, 85))
    world.srid = 4326
    features.append(
        {"type": "Feature", "properties": {"level": "country"}, "geometry": _rounded(country)}
    )
    features.append(
        {
            "type": "Feature",
            "properties": {"level": "mask"},
            "geometry": _rounded(world.difference(country)),
        }
    )
    data = {"type": "FeatureCollection", "bbox": list(country.extent), "features": features}
    cache.set(key, data, 60 * 60 * 24)
    return data
