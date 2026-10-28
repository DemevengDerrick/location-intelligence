"""Location check: computed vs stated area, admin units, nearest named quartier (TRD §4).

Two maps set the scene for non-specialist readers: the neighbourhood (roads, buildings,
rivers, the commune boundary and named places) and where the parcel lies in Cameroon. Their
context layers are optional: a missing data source leaves its layer out, never the section.
"""

import logging

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Polygon
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.gazetteer.boundaries import admin_units_at, commune_at
from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.parcels.validation import area_difference_pct

from .. import charts
from ..charts import series_scale
from ..config import thresholds
from ..formatting import fmt
from ..maps import ParcelMap, country_map
from ..models import ModuleStatus, Rating
from ..providers import buildings_provider, osm_provider, water_features_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

logger = logging.getLogger(__name__)

CAMEROON_BOX = (8.3, 1.6, 16.3, 13.2)
CONTEXT_RADIUS_M = 400  # the neighbourhood map: 400 m around the parcel
MAIN_ROADS = {"motorway", "trunk", "primary", "secondary", "tertiary"}
CITIES = [("Yaoundé", 11.5021, 3.8480), ("Douala", 9.7043, 4.0511)]  # reference points
NAMED_PLACES = [PlaceType.QUARTIER, PlaceType.VILLAGE, PlaceType.LIEU_DIT]


class LocationModule(Module):
    name = "location"
    title = gettext_lazy("Location and boundary")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        centre = geom.point_on_surface
        units = admin_units_at(geom)
        quartier = (
            GazetteerPlace.objects.filter(
                # 0.03° ≈ 3.3 km; dwithin on a 4326 geometry column takes degrees.
                place_type=PlaceType.QUARTIER,
                geometry__dwithin=(centre, 0.03),
            )
            .annotate(distance=Distance("geometry", centre))
            .order_by("distance")
            .first()
        )
        difference = (
            None
            if parcel.is_approximate
            else area_difference_pct(parcel.computed_area_m2, parcel.stated_area_m2)
        )
        results = {
            "computed_area_m2": parcel.computed_area_m2,
            "stated_area_m2": parcel.stated_area_m2,
            "difference_pct": difference,
            "approximate": parcel.is_approximate,
            "centroid": [round(centre.x, 6), round(centre.y, 6)],
            "region": units.region,
            "department": units.department,
            "commune": units.commune,
            "stated_commune": parcel.commune,
            "nearest_quartier": quartier.name if quartier else "",
            "vertices": []
            if parcel.is_approximate
            else [[round(x, 6), round(y, 6)] for x, y in geom[0][0].coords[:-1]],
        }
        if difference is None:
            rating = Rating.GREY
        elif abs(difference) <= t.area_amber_pct:
            rating = Rating.GREEN
        elif abs(difference) <= t.area_red_pct:
            rating = Rating.AMBER
        else:
            rating = Rating.RED

        datasets = {"geoboundaries-cmr-adm3": "gbOpen"}
        context = self._context(geom, centre, datasets)

        def draw():  # labels are translated here, in the language being drawn
            figure = ParcelMap(geom, extent=CONTEXT_RADIUS_M)
            self._draw_context(figure, context)
            figure.roads_drawn = bool(context["roads"])  # named roads drawn with the context
            label = (
                _("Approximate location (pin with buffer)")
                if parcel.is_approximate
                else _("Parcel boundary")
            )
            figure.add_parcel(geom, label)
            return figure.to_svg(context["source"]())

        def draw_country():
            return country_map(
                context["country"],
                context["regions"],
                context["region"],
                centre,
                CITIES,
                _("Regions: geoBoundaries (CC BY 3.0)."),
                {
                    "parcel": _("The parcel"),
                    "region": _("Its region: %(name)s") % {"name": context["region"].name}
                    if context["region"]
                    else _("Its region"),
                    "city": _("Main cities"),
                    "roads": _("National roads"),
                },
                roads=context["national_roads"],
            )

        maps = {"main": self.render_maps(draw)}
        if context["country"] is not None:
            maps["country"] = self.render_maps(draw_country)
            datasets["geoboundaries-cmr-adm1"] = "gbOpen"

        return ModuleOutput(
            status=ModuleStatus.OK if units.commune else ModuleStatus.WARNING,
            rating=rating,
            results=results,
            parameters={"area_amber_pct": t.area_amber_pct, "area_red_pct": t.area_red_pct},
            datasets=datasets,
            maps=maps,
            charts={"area": self._area_chart(results)},
        )

    def _context(self, geom, centre, datasets):
        """What the two maps show around the parcel; each layer is optional."""
        bounds = radius_bounds(centre, CONTEXT_RADIUS_M * 1.05)  # just what the map shows
        box = Polygon.from_bbox(bounds)
        box.srid = 4326
        context = {
            "buildings": [],
            "roads": [],
            "national_roads": [],
            "water": None,
            "commune": None,
            "places": [],
        }
        credits = []
        try:
            source = buildings_provider().fetch(*bounds)
            context["buildings"] = source.footprints
            datasets[source.dataset] = source.version
            credits.append(lambda: _("buildings: Google Open Buildings (CC BY 4.0)"))
        except Exception:
            logger.warning("Location map: no buildings", exc_info=True)
        try:
            osm = osm_provider()
            if osm is not None:
                from apps.osm.models import Category
                from apps.osm.queries import in_box

                context["roads"] = [
                    (f.geom, f.kind, f.name) for f in in_box(osm, Category.ROAD, *bounds)
                ]
                national = in_box(osm, Category.ROAD, *CAMEROON_BOX).filter(
                    kind__in=["motorway", "trunk"]
                )
                context["national_roads"] = [f.geom.simplify(0.01) for f in national]
                datasets["osm-roads-services"] = osm.data_timestamp[:10]
                credits.append(lambda: _("roads © OpenStreetMap contributors"))
        except Exception:
            logger.warning("Location map: no roads", exc_info=True)
        try:
            water = water_features_provider().fetch(*bounds)
            water.lines = [g for g in water.lines if g.intersects(box)]
            water.areas = [g for g in water.areas if g.intersects(box)]
            context["water"] = water
        except Exception:
            logger.warning("Location map: no rivers", exc_info=True)
        commune = commune_at(geom)
        if commune is not None and commune.geometry.boundary.intersects(box):
            context["commune"] = commune.geometry.boundary.intersection(box)
        context["places"] = [
            (place.geometry.centroid.x, place.geometry.centroid.y, place.name)
            for place in GazetteerPlace.objects.filter(
                place_type__in=NAMED_PLACES, geometry__intersects=box
            )[:40]
        ]
        context["country"] = (
            GazetteerPlace.objects.filter(place_type=PlaceType.COUNTRY)
            .values_list("geometry", flat=True)
            .first()
        )
        context["regions"] = list(GazetteerPlace.objects.filter(place_type=PlaceType.REGION))
        context["region"] = next(
            (r for r in context["regions"] if r.geometry.contains(centre)), None
        )
        context["source"] = lambda: (
            _("Boundary as supplied by the customer.")
            + (
                " "
                + _("Context: %(sources)s.")
                % {"sources": "; ".join(credit() for credit in credits)}
                if credits
                else ""
            )
        )
        return context

    @staticmethod
    def _draw_context(figure, context):
        for i, building in enumerate(context["buildings"]):
            figure.add(
                building,
                label=_("Buildings") if i == 0 else None,
                facecolor="#D9D9D9",
                edgecolor="#A0A0A0",
                linewidth=0.3,
                zorder=2,
            )
        water = context["water"]
        if water is not None:
            for i, area in enumerate(water.areas):
                figure.add(
                    area,
                    label=_("Water bodies") if i == 0 else None,
                    facecolor="#A6CEE3",
                    edgecolor="#1F78B4",
                    linewidth=0.5,
                    zorder=3,
                )
            for i, line in enumerate(water.lines):
                figure.add_line(
                    line, label=_("Rivers and streams") if i == 0 else None, color="#1F78B4"
                )
        first, named = True, {}
        for road, kind, name in context["roads"]:
            lines = list(road) if road.geom_type == "MultiLineString" else [road]
            for line in lines:
                figure.add_line(
                    line,
                    label=_("Roads") if first else None,
                    color="#555555",
                    linewidth=1.6 if kind in MAIN_ROADS else 0.7,
                )
                first = False
                if name and kind in MAIN_ROADS and line.length > named.get(name, (0, None))[0]:
                    named[name] = (line.length, line.interpolate_normalized(0.5))
        if context["commune"] is not None:
            boundary = context["commune"]
            lines = [g for g in _parts(boundary) if g.geom_type in ("LineString", "LinearRing")]
            for i, line in enumerate(lines):
                figure.add_line(
                    line,
                    label=_("Commune boundary") if i == 0 else None,
                    color="#7B3294",
                    linewidth=1.2,
                )
        figure.add_labels(context["places"])
        figure.add_labels(
            [(point.x, point.y, name) for name, (_length, point) in named.items()],
            size=6,
            colour="#444444",
        )

    def _area_chart(self, results):
        computed, stated, diff = (
            results["computed_area_m2"],
            results["stated_area_m2"],
            results["difference_pct"],
        )
        if diff is None:
            return {
                "reason": self.per_language(
                    lambda: _(
                        "No area comparison: only a pin was given, or the seller's area is unknown."
                    )
                )
            }

        def build():
            if abs(diff) < 0.5:
                title = _("The seller's area matches the boundary")
            elif diff < 0:
                title = _("The seller's area is %(pct)s %% smaller than the boundary") % {
                    "pct": fmt(abs(diff), 1)
                }
            else:
                title = _("The seller's area is %(pct)s %% larger than the boundary") % {
                    "pct": fmt(abs(diff), 1)
                }
            rows = [
                {
                    "what": str(_("Boundary (computed)")),
                    "m2": round(computed),
                    "series": "computed",
                },
                {"what": str(_("Stated by the seller")), "m2": round(stated), "series": "stated"},
            ]
            colour = series_scale(["computed", "stated"])
            return charts.spec(
                title=title,
                source=str(
                    _("Boundary supplied by the customer; area measured in the local UTM zone.")
                ),
                height=90,
                data={"values": rows},
                layer=[
                    {
                        "mark": {"type": "bar", "height": 22},
                        "encoding": {
                            "y": {"field": "what", "type": "nominal", "sort": None, "title": None},
                            "x": {"field": "m2", "type": "quantitative", "title": "m²"},
                            "color": {
                                "field": "series",
                                "type": "nominal",
                                "scale": colour,
                                "legend": None,
                            },
                        },
                    },
                    {
                        "mark": {"type": "text", "align": "left", "dx": 4},
                        "encoding": {
                            "y": {"field": "what", "type": "nominal", "sort": None},
                            "x": {"field": "m2", "type": "quantitative"},
                            "text": {"field": "m2", "type": "quantitative", "format": ",.0f"},
                        },
                    },
                ],
            )

        return self.per_language(build)

    def key_figure(self, results):
        if results["computed_area_m2"] is None:
            return results["commune"] or ""
        figure = f"{fmt(results['computed_area_m2'])} m²"
        if results["difference_pct"] is not None:
            figure += f" ({fmt(results['difference_pct'], 0)} %)"
        return figure

    def finding_values(self, results):
        return {
            "area": results["computed_area_m2"],
            "stated_area": results["stated_area_m2"],
            "difference": abs(results["difference_pct"])
            if results["difference_pct"] is not None
            else None,
            "commune": results["commune"] or _("an unknown commune"),
            "department": results["department"],
            "region": results["region"],
            # "Wouri, Littoral" without dangling commas when a level is unknown
            "admin_area": ", ".join(p for p in (results["department"], results["region"]) if p)
            or "–",
        }


def _parts(geom):
    """The single geometries inside a (multi) geometry or collection."""
    return list(geom) if geom.geom_type.startswith(("Multi", "Geometry")) else [geom]
