"""Buildings on and near the parcel (TRD §4). Source: the local copy of Google Open Buildings
(footprints detected from satellite imagery, manage.py load_buildings)."""

from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.parcels.geometry import utm_srid_for

from .. import style
from ..config import thresholds
from ..formatting import fmt
from ..layers import legend_entry, vector_layer
from ..layers import per_language as _per_language
from ..maps import ParcelMap
from ..models import Rating
from ..providers import buildings_provider
from .base import Module, ModuleOutput

FETCH_MARGIN_DEG = 0.001  # ≈ 110 m: covers the 20 m ring and the parcel-scale map


class BuildingsModule(Module):
    name = "buildings"
    title = gettext_lazy("Buildings on the parcel")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        west, south, east, north = geom.extent
        source = buildings_provider().fetch(
            west - FETCH_MARGIN_DEG,
            south - FETCH_MARGIN_DEG,
            east + FETCH_MARGIN_DEG,
            north + FETCH_MARGIN_DEG,
        )
        srid = utm_srid_for(geom)
        parcel_m = geom.transform(srid, clone=True)
        ring_m = parcel_m.buffer(t.building_buffer_m)

        inside, near, other = [], [], []
        footprint_m2 = 0.0
        confidences = source.confidences or [None] * len(source.footprints)
        score = {}
        for building, confidence in zip(source.footprints, confidences, strict=True):
            score[id(building)] = confidence
            if building.srid is None:  # providers return lon/lat footprints
                building.srid = 4326
            building_m = building.transform(srid, clone=True)
            if building_m.intersects(parcel_m):
                inside.append(building)
                footprint_m2 += building_m.intersection(parcel_m).area
            elif building_m.intersects(ring_m):
                near.append(building)
            else:
                other.append(building)

        results = {
            "inside_count": len(inside),
            "inside_footprint_m2": round(footprint_m2),
            "inside_share_pct": round(footprint_m2 / parcel_m.area * 100, 1)
            if parcel_m.area
            else 0,
            "near_count": len(near),
            "buffer_m": t.building_buffer_m,
            "min_confidence": t.building_min_confidence,
        }
        rating = Rating.RED if inside else Rating.AMBER if near else Rating.GREEN
        buffer_ll = ring_m.transform(4326, clone=True)

        def draw():
            figure = ParcelMap(geom)
            for group, colour, label in (
                (other, style.BUILDING_OTHER, _("Other buildings")),
                (
                    near,
                    style.BUILDING_NEAR,
                    _("Within %(m)s m of the boundary") % {"m": f"{t.building_buffer_m:g}"},
                ),
                (inside, style.BUILDING_INSIDE, _("On the parcel")),
            ):
                for i, building in enumerate(group):
                    figure.add(
                        building,
                        label=label if i == 0 else None,
                        facecolor=colour,
                        edgecolor="#333333",
                        linewidth=0.4,
                        zorder=5,
                    )
            figure.add(
                buffer_ll,
                label=_("%(m)s m around the boundary") % {"m": f"{t.building_buffer_m:g}"},
                **style.BUFFER,
            )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _("Buildings: Google Open Buildings %(version)s, CC BY 4.0.")
                % {"version": source.version}
            )

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "building_buffer_m": t.building_buffer_m,
                "building_min_confidence": t.building_min_confidence,
            },
            datasets={source.dataset: source.version},
            maps={"main": self.render_maps(draw)},
            layers=self._layers(inside, near, other, buffer_ll, t.building_buffer_m, score),
        )

    @staticmethod
    def _layers(inside, near, other, ring, buffer_m, score):
        groups = (
            (other, style.BUILDING_OTHER, lambda: _("Other buildings")),
            (
                near,
                style.BUILDING_NEAR,
                lambda: _("Within %(m)s m of the boundary") % {"m": f"{buffer_m:g}"},
            ),
            (inside, style.BUILDING_INSIDE, lambda: _("On the parcel")),
        )
        features = [
            (
                building,
                {
                    "color": style_colour,
                    "status": _per_language(label),
                    "confidence": _confidence(score.get(id(building))),
                },
            )
            for group, style_colour, label in groups
            for building in group
        ]
        return [
            vector_layer(
                "buildings",
                lambda: _("Buildings"),
                features,
                kind="fill",
                color=style.BUILDING_OTHER,
                outline="#333333",
                opacity=0.8,
                hover=[
                    ("status", lambda: _("Building")),
                    ("confidence", lambda: _("Detection confidence")),
                ],
                legend=[legend_entry(colour, label) for _g, colour, label in groups],
            ),
            vector_layer(
                "ring",
                lambda: _("%(m)s m around the boundary") % {"m": f"{buffer_m:g}"},
                [(ring, {})],
                kind="line",
                color="#333333",
                dash=True,
                width=1,
            ),
        ]

    def key_figure(self, results):
        return _("%(inside)s on the parcel · %(near)s nearby") % {
            "inside": fmt(results["inside_count"]),
            "near": fmt(results["near_count"]),
        }

    def finding_values(self, results):
        return {
            "inside_count": results["inside_count"],
            "inside_footprint": results["inside_footprint_m2"],
            "inside_share": results["inside_share_pct"],
            "near_count": results["near_count"],
            "buffer": results["buffer_m"],
        }


def _confidence(value):
    return "" if value is None else f"{round(value * 100)} %"
