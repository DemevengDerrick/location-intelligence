"""Check a customer-supplied parcel geometry before it is saved (FR-8, FR-9, FR-11)."""

from dataclasses import dataclass, field

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Point
from django.utils.formats import number_format
from django.utils.translation import gettext as _

from apps.gazetteer.boundaries import is_in_cameroon

from .config import intake_config
from .geometry import area_m2, to_multipolygon, utm_srid_for
from .parsers import GeometryInputError


@dataclass
class CheckedParcel:
    geometry: MultiPolygon
    area_m2: float
    is_approximate: bool = False
    warnings: list[str] = field(default_factory=list)


def buffer_pin(point: Point, radius_m: float) -> MultiPolygon:
    """A circle of `radius_m` metres around the pin, built in the local UTM zone."""
    projected = point.transform(utm_srid_for(point), clone=True)
    circle = projected.buffer(radius_m, quadsegs=16)
    circle.srid = projected.srid
    return to_multipolygon(circle.transform(4326, clone=True))


def check_pin(point: Point) -> CheckedParcel:
    if not is_in_cameroon(point):
        raise GeometryInputError(_("This location is outside Cameroon."))
    radius = intake_config().pin_buffer_m
    geometry = buffer_pin(point, radius)
    return CheckedParcel(
        geometry,
        area_m2(geometry),
        is_approximate=True,
        warnings=[
            _(
                "Only a pin was given. We will analyse a %(radius)s m circle around it and mark "
                "the location as approximate in the report."
            )
            % {"radius": number_format(radius, 0)}
        ],
    )


def check_polygon(geom: GEOSGeometry) -> CheckedParcel:
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise GeometryInputError(_("The boundary must be a closed shape with at least 3 corners."))
    if not geom.valid:
        geom = _repair(geom)
    geometry = to_multipolygon(geom)
    if not is_in_cameroon(geometry):
        raise GeometryInputError(
            _("This boundary is outside Cameroon. Check the coordinates or the coordinate system.")
        )

    area = area_m2(geometry)
    config = intake_config()
    warnings = []
    if area < config.min_area_m2:
        warnings.append(
            _("The parcel is very small (%(area)s m²). Please check the boundary.")
            % {"area": number_format(area, 0, force_grouping=True)}
        )
    if area > config.max_area_m2:
        warnings.append(
            _("The parcel is very large (%(area)s ha). Please check the boundary.")
            % {"area": number_format(area / 10_000, 1, force_grouping=True)}
        )
    if len(geometry) > 1:
        warnings.append(_("The boundary has %(count)s separate parts.") % {"count": len(geometry)})
    return CheckedParcel(geometry, area, warnings=warnings)


def _repair(geom):
    """Fix self-intersections, keeping only the polygonal parts."""
    fixed = geom.make_valid()
    parts = []
    for part in fixed if fixed.geom_type in ("GeometryCollection", "MultiPolygon") else [fixed]:
        if part.geom_type == "Polygon":
            parts.append(part)
        elif part.geom_type == "MultiPolygon":
            parts.extend(part)
    if not parts:
        raise GeometryInputError(_("The boundary crosses itself and could not be repaired."))
    return MultiPolygon(*parts, srid=geom.srid)


def area_difference_pct(computed_m2, stated_m2):
    """Signed difference of the stated area relative to the computed one, in percent."""
    if not computed_m2 or not stated_m2:
        return None
    return (stated_m2 - computed_m2) / computed_m2 * 100
