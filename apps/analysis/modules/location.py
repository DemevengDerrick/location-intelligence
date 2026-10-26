"""Location check: computed vs stated area, admin units, nearest named quartier (TRD §4)."""

from django.contrib.gis.db.models.functions import Distance
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.gazetteer.boundaries import admin_units_at
from apps.gazetteer.models import GazetteerPlace, PlaceType
from apps.parcels.validation import area_difference_pct

from .. import charts
from ..charts import series_scale
from ..config import thresholds
from ..formatting import fmt
from ..maps import ParcelMap
from ..models import ModuleStatus, Rating
from .base import Module, ModuleOutput


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

        def draw():
            figure = ParcelMap(geom)
            label = (
                _("Approximate location (pin with buffer)")
                if parcel.is_approximate
                else _("Parcel boundary")
            )
            figure.add_parcel(geom, label)
            return figure.to_svg(_("Boundary as supplied by the customer."))

        return ModuleOutput(
            status=ModuleStatus.OK if units.commune else ModuleStatus.WARNING,
            rating=rating,
            results=results,
            parameters={"area_amber_pct": t.area_amber_pct, "area_red_pct": t.area_red_pct},
            datasets={"geoboundaries-cmr-adm3": "gbOpen"},
            maps={"main": self.render_maps(draw)},
            charts={"area": self._area_chart(results)},
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
