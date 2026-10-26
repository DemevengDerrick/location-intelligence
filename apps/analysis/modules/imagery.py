"""Current imagery and occupation: a recent cloud-free Sentinel-2 view of the parcel and its
1 km surroundings, and how much of the parcel is vegetated (TRD §4).

Pixels cannot separate buildings from bare soil (see landcover), so this section rates at most
amber; whether the parcel is built on is the Buildings section's job.
"""

import math
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.formats import date_format
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from .. import charts, style
from ..config import thresholds
from ..formatting import fmt
from ..landcover import classify, parcel_mask, shares, true_colour
from ..maps import NEIGHBOURHOOD_RADIUS_M, ParcelMap
from ..models import ModuleStatus, Rating
from ..providers import imagery_provider
from .base import Module, ModuleOutput

MIN_COVERAGE_PCT = 50  # below this share of clear pixels, land cover is not reported
COVER_CLASSES = ("vegetation", "open", "water")


def radius_bounds(point, radius_m):
    """A lon/lat box of `radius_m` around a point."""
    dlat = radius_m / 110_574
    dlon = radius_m / (111_320 * math.cos(math.radians(point.y)))
    return point.x - dlon, point.y - dlat, point.x + dlon, point.y + dlat


def month_range(start_iso, end_iso):
    """ "Dec 2025 – Feb 2026" in the active language."""
    start, end = parse_date(start_iso), parse_date(end_iso)
    first, last = date_format(start, "YEAR_MONTH_FORMAT"), date_format(end, "YEAR_MONTH_FORMAT")
    return first if first == last else f"{first} – {last}"


def cover_label(name):
    return {
        "vegetation": _("Vegetation"),
        "open": _("Built-up or bare ground"),
        "water": _("Water"),
    }[name]


def cover_encoding():
    """Shared colour encoding for the land-cover classes (same colours in every chart)."""
    return {
        "field": "cover",
        "type": "nominal",
        "title": None,
        "scale": {
            "domain": [str(cover_label(n)) for n in COVER_CLASSES],
            "range": [style.SERIES[n] for n in COVER_CLASSES],
        },
    }


class ImageryModule(Module):
    name = "imagery"
    title = gettext_lazy("Recent imagery and land cover")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        today = timezone.now().date()
        composite = imagery_provider().composite(
            *radius_bounds(geom.centroid, NEIGHBOURHOOD_RADIUS_M * 1.1),
            today - timedelta(days=365),
            today,
        )
        if composite is None:
            raise ValueError("No Sentinel-2 scene below the cloud limit in the last 12 months")

        classes = classify(composite.bands, t)
        mask = parcel_mask(geom, composite.crs_epsg, composite.transform, classes.shape)
        cover = shares(classes, mask)
        dates = composite.scene_dates
        results = {**cover, "scene_dates": dates, "period_start": dates[0], "period_end": dates[-1]}

        if cover["coverage_pct"] < MIN_COVERAGE_PCT:
            status, rating = ModuleStatus.WARNING, Rating.GREY
        elif cover["open"] >= t.open_amber_pct:
            status, rating = ModuleStatus.OK, Rating.AMBER
        else:
            status, rating = ModuleStatus.OK, Rating.GREEN

        rgb = true_colour(composite.bands)

        def source():
            return _(
                "Contains modified Copernicus Sentinel data %(year)s: median of %(n)s scenes, "
                "%(period)s."
            ) % {"year": dates[-1][:4], "n": len(dates), "period": month_range(dates[0], dates[-1])}

        def draw():
            figure = ParcelMap(geom, extent="neighbourhood")
            figure.add_rgb(rgb, composite.transform, composite.crs_epsg)
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(source())

        def cover_chart():
            rows = [
                {"cover": str(cover_label(name)), "pct": cover[name], "order": i}
                for i, name in enumerate(COVER_CLASSES)
            ]
            return charts.spec(
                title=_("About %(pct)s %% of the parcel is vegetated")
                % {"pct": fmt(cover["vegetation"], 0)},
                source=source(),
                height=40,
                data={"values": rows},
                mark={"type": "bar", "height": 28},
                encoding={
                    "x": {
                        "field": "pct",
                        "type": "quantitative",
                        "stack": "zero",
                        "title": str(_("Share of the parcel (%)")),
                        "scale": {"domain": [0, 100]},
                    },
                    "color": cover_encoding(),
                    "order": {"field": "order"},
                    "tooltip": [{"field": "cover"}, {"field": "pct", "format": ".1f"}],
                },
            )

        return ModuleOutput(
            status=status,
            rating=rating,
            results=results,
            parameters={"open_amber_pct": t.open_amber_pct, "ndvi_vegetation": t.ndvi_vegetation},
            datasets={composite.dataset: f"L2A {dates[0]} – {dates[-1]}"},
            maps={"main": self.render_maps(draw)},
            charts={"cover": self.per_language(cover_chart)},
        )

    def finding_values(self, results):
        return {
            "vegetation": results["vegetation"],
            "open": results["open"],
            "water": results["water"],
            "period": month_range(results["period_start"], results["period_end"]),
        }

    def key_figure(self, results):
        return _("%(pct)s %% vegetated") % {"pct": fmt(results["vegetation"], 0)}
