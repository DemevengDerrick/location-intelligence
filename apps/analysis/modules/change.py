"""Change over time: one dry-season Sentinel-2 composite per year since 2017, the vegetated
share of the parcel each year, and when parts of it were cleared (TRD §4, "Occupation and
change"). Dry season (December–February) gives the fewest clouds in southern Cameroon.

Clearing means vegetation turned into built-up or bare ground; pixels cannot say which (see
landcover). Buildings come from the Buildings section.
"""

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from matplotlib import colormaps

from .. import charts
from ..config import thresholds
from ..formatting import fmt
from ..landcover import OPEN, VEGETATION, classify, parcel_mask, shares, true_colour
from ..maps import ParcelMap, image_strip
from ..models import ModuleStatus, Rating
from ..providers import imagery_provider
from .base import Module, ModuleOutput
from .imagery import COVER_CLASSES, MIN_COVERAGE_PCT, cover_encoding, cover_label, radius_bounds

MIN_YEARS = 3
RECENT_YEARS = 5  # clearing is measured over this many years


def season_years(first_year, today):
    """Years whose December–February dry season is complete (season Y = Dec Y-1 to Feb Y)."""
    last = today.year if today.month >= 3 else today.year - 1
    return list(range(int(first_year), last + 1))


def first_cleared_year(stack):
    """Per pixel, the first year from which it stays non-vegetated in every later observation,
    if it was vegetated in the first one; NaN otherwise."""
    years = [year for year, _classes in stack]
    vegetated_first = stack[0][1] == VEGETATION
    cleared = np.stack([classes == OPEN for _year, classes in stack])
    observed = np.stack([classes > 0 for _year, classes in stack])
    result = np.full(vegetated_first.shape, np.nan)
    for i, year in enumerate(years[1:], start=1):
        stays_cleared = np.all(cleared[i:] | ~observed[i:], axis=0) & cleared[i]
        new = stays_cleared & vegetated_first & np.isnan(result)
        result[new] = year
    return result


class ChangeModule(Module):
    name = "change"
    title = gettext_lazy("Change over time")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        provider = imagery_provider()
        bounds = radius_bounds(geom.centroid, _parcel_radius_m(geom) + 60)
        years = season_years(t.change_first_year, timezone.now().date())

        def fetch(year):
            return year, provider.composite(*bounds, date(year - 1, 12, 1), date(year, 2, 28))

        with ThreadPoolExecutor(max_workers=3) as pool:
            composites = list(pool.map(fetch, years))

        series, frames, stack, grid = [], [], [], None
        for year, composite in composites:
            if composite is None:
                continue
            classes = classify(composite.bands, t)
            mask = parcel_mask(geom, composite.crs_epsg, composite.transform, classes.shape)
            cover = shares(classes, mask)
            if cover["coverage_pct"] < MIN_COVERAGE_PCT:
                continue
            series.append({"year": year, **cover})
            frames.append(
                (str(year), true_colour(composite.bands), composite.transform, composite.crs_epsg)
            )
            stack.append((year, classes))
            grid = (composite.transform, composite.crs_epsg, mask)

        if len(series) < MIN_YEARS:
            return ModuleOutput(
                status=ModuleStatus.WARNING,
                rating=Rating.GREY,
                results={"series": series, "years_requested": years},
                datasets={"sentinel-2-l2a": "L2A dry-season composites"},
            )

        first, last = series[0], series[-1]
        reference = max(
            (row for row in series if row["year"] <= last["year"] - RECENT_YEARS),
            key=lambda row: row["year"],
            default=first,
        )
        recent_loss = reference["vegetation"] - last["vegetation"]
        rating = Rating.AMBER if recent_loss >= t.clearing_amber_pts else Rating.GREEN

        cleared = first_cleared_year(stack)
        transform, crs_epsg, mask = grid
        cleared[~mask] = np.nan
        cleared_years = sorted({int(y) for y in cleared[np.isfinite(cleared)]})
        results = {
            "series": series,
            "first_year": first["year"],
            "last_year": last["year"],
            "reference_year": reference["year"],
            "vegetation_first": first["vegetation"],
            "vegetation_reference": reference["vegetation"],
            "vegetation_last": last["vegetation"],
            "open_first": first["open"],
            "open_last": last["open"],
            "vegetation_loss_recent_pts": round(recent_loss, 1),
            "cleared_years": cleared_years,
        }

        def source():
            return _(
                "Contains modified Copernicus Sentinel data %(first)s–%(last)s, "
                "dry-season composites."
            ) % {"first": first["year"], "last": last["year"]}

        def draw_strip():
            return image_strip(frames, geom, source())

        def draw_clearing():
            figure = ParcelMap(geom)
            if cleared_years:
                palette = colormaps["viridis"].resampled(max(len(cleared_years), 2))
                figure.add_classified_raster(
                    cleared,
                    transform,
                    [cleared_years[0] - 0.5] + [y + 0.5 for y in cleared_years],
                    [palette(i) for i in range(len(cleared_years))],
                    [_("Cleared from %(y)s") % {"y": y} for y in cleared_years],
                    crs_epsg=crs_epsg,
                )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(source())

        def trend_chart():
            rows = [
                {"year": row["year"], "cover": str(cover_label(name)), "pct": row[name], "order": i}
                for row in series
                for i, name in enumerate(COVER_CLASSES)
            ]
            return charts.spec(
                title=_("Vegetation went from %(a)s %% in %(y1)s to %(b)s %% in %(y2)s")
                % {
                    "a": fmt(first["vegetation"], 0),
                    "y1": first["year"],
                    "b": fmt(last["vegetation"], 0),
                    "y2": last["year"],
                },
                source=source(),
                data={"values": rows},
                mark={"type": "area"},
                encoding={
                    "x": {"field": "year", "type": "ordinal", "title": None},
                    "y": {
                        "field": "pct",
                        "type": "quantitative",
                        "stack": "zero",
                        "title": str(_("Share of the parcel (%)")),
                        "scale": {"domain": [0, 100]},
                    },
                    "color": cover_encoding(),
                    "order": {"field": "order"},
                },
            )

        maps = {"strip": self.render_maps(draw_strip)}
        charts_out = {"trend": self.per_language(trend_chart)}
        if cleared_years:
            maps["clearing"] = self.render_maps(draw_clearing)
        else:  # nothing to map: say so instead of an empty map (FR-68)
            charts_out["clearing"] = {
                "reason": self.per_language(
                    lambda: (
                        _("No part of the parcel was cleared between %(a)s and %(b)s.")
                        % {"a": first["year"], "b": last["year"]}
                    )
                )
            }

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "clearing_amber_pts": t.clearing_amber_pts,
                "ndvi_vegetation": t.ndvi_vegetation,
                "first_year": t.change_first_year,
            },
            datasets={"sentinel-2-l2a": f"L2A dry seasons {first['year']}–{last['year']}"},
            maps=maps,
            charts=charts_out,
        )

    def finding_values(self, results):
        if "first_year" not in results:
            return {}
        return {
            "first_year": str(results["first_year"]),
            "last_year": str(results["last_year"]),
            "ref_year": str(results["reference_year"]),
            "veg_first": results["vegetation_first"],
            "veg_ref": results["vegetation_reference"],
            "veg_last": results["vegetation_last"],
            "open_first": results["open_first"],
            "open_last": results["open_last"],
        }

    def key_figure(self, results):
        if "vegetation_loss_recent_pts" not in results:
            return ""
        delta = round(-results["vegetation_loss_recent_pts"])  # change in vegetation, points
        return _("%(delta)s pts vegetation since %(year)s") % {
            "delta": ("+" if delta > 0 else "") + fmt(delta + 0, 0),  # + 0 turns -0 into 0
            "year": results["reference_year"],
        }


def _parcel_radius_m(geom):
    west, south, east, north = geom.extent
    width = (east - west) * 111_320 * math.cos(math.radians(geom.centroid.y))
    return max(width, (north - south) * 110_574) / 2
