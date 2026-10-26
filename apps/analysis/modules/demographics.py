"""Demographics and area growth (TRD §4.1): the people living around the parcel, not on it.

Areas are a 1 km and a 5 km circle around the parcel, plus its commune. Figures come from
WorldPop R2025A age-sex rasters (2020, 2025, and the 2030 projection); built-up growth from
GHSL. They are modelled estimates, not census counts, and less certain for small areas.
"""

import numpy as np
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.gazetteer.boundaries import commune_at
from apps.parcels.geometry import utm_srid_for

from .. import style
from ..charts import spec
from ..config import thresholds
from ..formatting import fmt
from ..maps import AREA_RADIUS_M, ParcelMap
from ..models import Rating
from ..population import BANDS, cached_age_sex, population_provider
from ..providers import ghsl_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

RADII_M = {"1km": 1_000, "5km": 5_000}
BASE_YEAR, CURRENT_YEAR, PROJECTED_YEAR = 2020, 2025, 2030
DENSITY_CLASSES = [0.5, 500, 2_000, 5_000, 10_000, 1e9]  # people per km²
DENSITY_COLOURS = ["#F2F0F7", "#CBC9E2", "#9E9AC8", "#756BB1", "#54278F"]
EPOCH_COLOURS = ["#4D4D4D", "#8C510A", "#D8B365", "#F6A04D", "#E6550D"]  # oldest to newest
GROUPS = ["under_5", "5_14", "15_64", "65_plus"]


def circle(parcel_geom, radius_m):
    centre = parcel_geom.centroid
    srid = utm_srid_for(centre)
    return centre.transform(srid, clone=True).buffer(radius_m, 32).transform(4326, clone=True)


def annual_rate(start, end, years):
    if not start or not end:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def area_labels(commune_name):
    return {
        "1km": _("Within 1 km"),
        "5km": _("Within 5 km"),
        "commune": _("Commune of %(name)s") % {"name": commune_name} if commune_name else "",
    }


class DemographicsModule(Module):
    name = "demographics"
    title = gettext_lazy("Demographics and area growth")

    def run(self, parcel):
        t = thresholds()
        provider = population_provider()
        years = provider.years()
        if not {BASE_YEAR, CURRENT_YEAR} <= set(years):
            raise RuntimeError("WorldPop rasters are not loaded (manage.py load_worldpop)")
        geom = parcel.geometry
        areas = {key: circle(geom, radius) for key, radius in RADII_M.items()}
        commune = commune_at(geom)
        if commune is not None:
            areas["commune"] = commune.geometry

        stats = {
            key: {year: cached_age_sex(provider, area, year) for year in years}
            for key, area in areas.items()
        }
        results = {
            "release": provider.release,
            "years": years,
            "projected_years": [y for y in years if y >= 2026],
            "commune": commune.name if commune else None,
            "areas": {},
        }
        for key, area in areas.items():
            km2 = area.transform(utm_srid_for(area.centroid), clone=True).area / 1e6
            totals = {str(y): round(s.total) for y, s in stats[key].items()}
            results["areas"][key] = {
                "area_km2": round(km2, 2),
                "population": totals,
                "density": {y: round(n / km2) for y, n in totals.items()},
                "growth_pct": annual_rate(
                    stats[key][BASE_YEAR].total, stats[key][CURRENT_YEAR].total, 5
                ),
                "projected_growth_pct": annual_rate(
                    stats[key][CURRENT_YEAR].total, stats[key].get(PROJECTED_YEAR).total, 5
                )
                if PROJECTED_YEAR in stats[key]
                else None,
                "pyramid": stats[key][CURRENT_YEAR].pyramid(),
                "groups": stats[key][CURRENT_YEAR].groups(),
            }

        ghsl = ghsl_provider()
        bounds = radius_bounds(geom.centroid, AREA_RADIUS_M * 1.05)
        built = {epoch: ghsl.built(*bounds, epoch) for epoch in ghsl.EPOCHS}
        first_epoch, built_km2 = self._expansion(built, areas["5km"], t.ghsl_built_share)
        results["built_km2"] = built_km2
        results["rating_basis"] = "5km"
        rating = self._rate(results["areas"]["5km"]["growth_pct"], t)

        density = provider.density(*bounds, CURRENT_YEAR)

        def draw_density():
            labels = area_labels(results["commune"])  # in the language being drawn
            figure = ParcelMap(geom, extent="area")
            figure.add_classified_raster(
                np.where(density.values > 0.5, density.values, np.nan),
                density.transform,
                DENSITY_CLASSES,
                DENSITY_COLOURS,
                [
                    _("Under 500 people/km²"),
                    "500–2,000",
                    "2,000–5,000",
                    "5,000–10,000",
                    _("Over 10,000"),
                ],
            )
            for key in ("1km", "5km"):
                figure.add(
                    areas[key],
                    label=labels[key],
                    facecolor="none",
                    edgecolor="#222222",
                    linestyle="--",
                    linewidth=1.0,
                    zorder=5,
                )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Population density in %(year)s from WorldPop %(release)s (100 m grid, CC BY "
                    "4.0): modelled estimates, not census counts."
                )
                % {"year": CURRENT_YEAR, "release": provider.release}
            )

        def draw_expansion():
            labels = area_labels(results["commune"])
            figure = ParcelMap(geom, extent="area")
            epoch_labels = [_("Built by %(y)s") % {"y": ghsl.EPOCHS[0]}] + [
                f"{a}–{b}" for a, b in zip(ghsl.EPOCHS, ghsl.EPOCHS[1:], strict=False)
            ]
            figure.add_classified_raster(
                first_epoch.values,
                first_epoch.transform,
                [0.5 + i for i in range(len(ghsl.EPOCHS) + 1)],
                EPOCH_COLOURS[: len(ghsl.EPOCHS)],
                epoch_labels,
            )
            figure.add(
                areas["5km"],
                label=labels["5km"],
                facecolor="none",
                edgecolor="#222222",
                linestyle="--",
                linewidth=1.0,
                zorder=5,
            )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Built-up areas by period from GHSL GHS-BUILT-S %(v)s (EC JRC, CC BY 4.0), "
                    "cells at least %(pct)s %% built."
                )
                % {"v": ghsl.version, "pct": fmt(t.ghsl_built_share * 100, 0)}
            )

        charts = {
            "pyramid": self.per_language(lambda: self._pyramid_chart(results, provider)),
            "growth": self.per_language(lambda: self._growth_chart(results, provider)),
            "groups": self.per_language(lambda: self._groups_chart(results, provider)),
            "areas": {"table": self.per_language(lambda: self._table(results))},
        }
        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "growth_green_pct": t.growth_green_pct,
                "growth_red_pct": t.growth_red_pct,
                "ghsl_built_share": t.ghsl_built_share,
                "radii_m": RADII_M,
            },
            datasets={provider.dataset: provider.release, ghsl.dataset: ghsl.version},
            maps={
                "density": self.render_maps(draw_density),
                "expansion": self.render_maps(draw_expansion),
            },
            charts=charts,
        )

    @staticmethod
    def _expansion(built, area, share):
        """The epoch each cell first became built-up (1-based class), and the built-up km²
        within the area for each epoch."""
        import json

        from rasterio.features import geometry_mask

        from ..providers import Grid

        epochs = sorted(built)
        reference = built[epochs[-1]]
        lat = area.centroid.y
        cell_m2 = (abs(reference.transform.a) * 111_320 * np.cos(np.radians(lat))) * (
            abs(reference.transform.e) * 110_574
        )
        first = np.full(reference.values.shape, np.nan, dtype="float32")
        inside = geometry_mask(
            [json.loads(area.json)],
            out_shape=first.shape,
            transform=reference.transform,
            invert=True,
        )
        km2 = {}
        for index, epoch in enumerate(epochs, start=1):
            is_built = built[epoch].values / cell_m2 >= share
            first[np.isnan(first) & is_built] = index
            km2[str(epoch)] = round(float(built[epoch].values[inside].sum()) / 1e6, 2)
        return Grid(first, reference.transform), km2

    @staticmethod
    def _rate(growth, t):
        if growth is None:
            return Rating.GREY
        if growth < t.growth_red_pct:
            return Rating.RED
        if growth < t.growth_green_pct:
            return Rating.AMBER
        return Rating.GREEN

    def _source(self, provider, extra=""):
        text = _("WorldPop %(release)s: modelled estimates, not census counts.") % {
            "release": provider.release
        }
        return f"{text} {extra}".strip()

    def _pyramid_chart(self, r, provider):
        labels = area_labels(r["commune"])
        rows = []
        for key in ("5km", "commune"):
            if key not in r["areas"]:
                continue
            pyramid = r["areas"][key]["pyramid"]
            for i, band in enumerate(BANDS):
                rows.append(
                    {
                        "band": band,
                        "sex": _("Male"),
                        "share": -pyramid["male"][i],
                        "area": str(labels[key]),
                    }
                )
                rows.append(
                    {
                        "band": band,
                        "sex": _("Female"),
                        "share": pyramid["female"][i],
                        "area": str(labels[key]),
                    }
                )
        under15 = r["areas"]["5km"]["groups"]["under_15"]
        y = {"field": "band", "type": "ordinal", "sort": list(reversed(BANDS)), "title": None}
        x = {
            "field": "share",
            "type": "quantitative",
            "title": _("Share of the population (%)"),
            "axis": {"labelExpr": "abs(datum.value)"},
        }
        layers = [
            {
                "transform": [{"filter": {"field": "area", "equal": str(labels["5km"])}}],
                "mark": {"type": "bar"},
                "encoding": {
                    "y": y,
                    "x": x,
                    "color": {
                        "field": "sex",
                        "type": "nominal",
                        "title": None,
                        "scale": {
                            "domain": [_("Male"), _("Female")],
                            "range": [style.SERIES["male"], style.SERIES["female"]],
                        },
                    },
                },
            }
        ]
        if r["commune"]:
            layers.append(
                {
                    "transform": [{"filter": {"field": "area", "equal": str(labels["commune"])}}],
                    "mark": {
                        "type": "bar",
                        "fillOpacity": 0,
                        "stroke": "#222222",
                        "strokeWidth": 1,
                    },
                    "encoding": {"y": y, "x": x},
                }
            )
        outline = (
            _("Bars: within 5 km in %(year)s. Outline: commune of %(name)s.")
            % {"year": CURRENT_YEAR, "name": r["commune"]}
            if r["commune"]
            else _("Within 5 km in %(year)s.") % {"year": CURRENT_YEAR}
        )
        return spec(
            title=_("%(pct)s %% of people within 5 km are under 15") % {"pct": fmt(under15)},
            source=[
                self._source(provider),
                outline,
                _(
                    "WorldPop models age structure per administrative unit, so it "
                    "varies little between nearby areas."
                ),
            ],
            height=260,
            data={"values": rows},
            layer=layers,
        )

    def _growth_chart(self, r, provider):
        five = r["areas"]["5km"]["population"]
        estimate, projection = _("Estimate"), _("Projection")
        rows = []
        for year, people in sorted(five.items()):
            year = int(year)
            if year <= CURRENT_YEAR:
                rows.append({"year": year, "people": people, "kind": estimate})
            if year >= CURRENT_YEAR:
                rows.append({"year": year, "people": people, "kind": projection})
        growth = r["areas"]["5km"]["growth_pct"]
        return spec(
            title=_("Population within 5 km: %(rate)s %% a year from %(a)s to %(b)s")
            % {"rate": _signed(growth), "a": BASE_YEAR, "b": CURRENT_YEAR},
            source=self._source(provider, _("Dashed: projection.")),
            height=180,
            data={"values": rows},
            mark={"type": "line", "point": True},
            encoding={
                "x": {"field": "year", "type": "ordinal", "title": None, "axis": {"labelAngle": 0}},
                "y": {
                    "field": "people",
                    "type": "quantitative",
                    "title": _("People"),
                    "scale": {"zero": False},
                    "axis": {"format": ",.0f"},
                },
                "strokeDash": {
                    "field": "kind",
                    "type": "nominal",
                    "title": None,
                    "scale": {"domain": [estimate, projection], "range": [[1, 0], [5, 4]]},
                },
                "color": {"value": style.SERIES["computed"]},
            },
        )

    def _groups_chart(self, r, provider):
        labels = area_labels(r["commune"])
        names = {
            "under_5": _("Under 5"),
            "5_14": _("5–14 (school age)"),
            "15_64": _("15–64"),
            "65_plus": _("65 and over"),
        }
        rows = []
        for key in ("5km", "commune"):
            if key in r["areas"]:
                for group in GROUPS:
                    rows.append(
                        {
                            "group": str(names[group]),
                            "area": str(labels[key]),
                            "share": r["areas"][key]["groups"][group],
                        }
                    )
        ratio = r["areas"]["5km"]["groups"]["dependency_ratio"]
        return spec(
            title=_("%(ratio)s dependants for every 100 people aged 15–64 within 5 km")
            % {"ratio": fmt(ratio, 0)},
            source=self._source(provider, str(CURRENT_YEAR)),
            height=160,
            data={"values": rows},
            mark={"type": "bar"},
            encoding={
                "x": {
                    "field": "group",
                    "type": "nominal",
                    "title": None,
                    "sort": [str(names[g]) for g in GROUPS],
                    "axis": {"labelAngle": 0},
                },
                "xOffset": {"field": "area"},
                "y": {
                    "field": "share",
                    "type": "quantitative",
                    "title": _("Share of the population (%)"),
                },
                "color": {
                    "field": "area",
                    "type": "nominal",
                    "title": None,
                    "scale": {
                        "domain": [str(labels["5km"]), str(labels["commune"])],
                        "range": [style.SERIES["computed"], style.SERIES["comparison"]],
                    },
                },
            },
        )

    @staticmethod
    def _table(r):
        labels = area_labels(r["commune"])
        rows = []
        for key in ("1km", "5km", "commune"):
            area = r["areas"].get(key)
            if area is None:
                continue
            rows.append(
                [
                    str(labels[key]),
                    fmt(area["population"][str(CURRENT_YEAR)]),
                    fmt(area["density"][str(CURRENT_YEAR)]),
                    _signed(area["growth_pct"]) + " %",
                    _signed(area["projected_growth_pct"]) + " %",
                ]
            )
        return {
            "caption": _("Population in %(year)s (WorldPop %(release)s)")
            % {"year": CURRENT_YEAR, "release": r["release"]},
            "columns": [
                _("Area"),
                _("People"),
                _("Per km²"),
                _("Growth a year, %(a)s–%(b)s") % {"a": BASE_YEAR, "b": CURRENT_YEAR},
                _("Projected, %(a)s–%(b)s") % {"a": CURRENT_YEAR, "b": PROJECTED_YEAR},
            ],
            "rows": rows,
        }

    def finding_values(self, results):
        five = results["areas"]["5km"]
        built = results.get("built_km2") or {}
        epochs = sorted(built)
        if len(epochs) >= 2 and built[epochs[0]]:
            expansion = _(
                "Built-up land within 5 km grew from %(a)s km² in %(y1)s to %(b)s km² in %(y2)s."
            ) % {
                "a": fmt(built[epochs[0]], 1),
                "y1": epochs[0],
                "b": fmt(built[epochs[-1]], 1),
                "y2": epochs[-1],
            }
        else:
            expansion = ""
        return {
            "people": _round_people(five["population"][str(CURRENT_YEAR)]),
            "density": fmt(five["density"][str(CURRENT_YEAR)]),
            "growth": _signed(five["growth_pct"]),
            "projected": _signed(five["projected_growth_pct"]),
            "y1": str(BASE_YEAR),  # text: years take no thousands separator
            "y2": str(CURRENT_YEAR),
            "y3": str(PROJECTED_YEAR),
            "under15": fmt(five["groups"]["under_15"]),
            "expansion": expansion,
            "release": results["release"],
        }

    def key_figure(self, results):
        five = results["areas"]["5km"]
        return _("%(n)s people within 5 km · %(g)s %%/yr") % {
            "n": _round_people(five["population"][str(CURRENT_YEAR)]),
            "g": _signed(five["growth_pct"]),
        }


def _signed(value):
    if value is None:
        return "–"
    value = round(value, 1) + 0  # no "-0"
    return ("+" if value > 0 else "") + fmt(value, 1)


def _round_people(n):
    """Modelled figures are rounded to the nearest 100 (1,000 above 100,000)."""
    step = 1000 if n >= 100_000 else 100
    return fmt(round(n / step) * step)
