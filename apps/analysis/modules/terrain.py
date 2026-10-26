"""Terrain: elevation, slope and erosion-prone share of the parcel (TRD §4).

Copernicus GLO-30 is a surface model: in built-up areas buildings and trees add relief, so
slopes are indicative. The report's limitations section says so.
"""

import json
import math

import numpy as np
from django.contrib.gis.geos import Point
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from rasterio.features import geometry_mask

from apps.parcels.geometry import utm_srid_for

from .. import charts, style
from ..config import thresholds
from ..formatting import fmt
from ..layers import classified_layer
from ..maps import ParcelMap
from ..models import Rating
from ..providers import elevation_provider
from .base import Module, ModuleOutput

DEM_MARGIN_DEG = 0.003  # ≈ 330 m around the parcel, enough for the map and the slope kernel


def slope_degrees(heights, transform, latitude):
    """Slope per cell, from a lon/lat grid converted to metres at the given latitude."""
    cell_x = abs(transform.a) * 111_320 * math.cos(math.radians(latitude))
    cell_y = abs(transform.e) * 110_574
    dz_dy, dz_dx = np.gradient(heights.astype("float64"), cell_y, cell_x)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))


def elevation_profile(geom, dem, samples=60):
    """Elevation along the parcel's longest axis, from 50 m before to 50 m after it."""
    srid = utm_srid_for(geom)
    parcel_m = geom.transform(srid, clone=True)
    vertices = [xy for polygon in parcel_m for xy in polygon.exterior_ring.coords]
    (x1, y1), (x2, y2) = max(
        ((a, b) for a in vertices for b in vertices), key=lambda ab: math.dist(*ab)
    )
    length = math.dist((x1, y1), (x2, y2)) or 1.0
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    cx, cy = parcel_m.centroid.coords
    offsets = [(x - cx) * ux + (y - cy) * uy for x, y in vertices]
    start, end = min(offsets) - 50, max(offsets) + 50
    inverse = ~dem.transform
    rows = []
    for i in range(samples):
        t = start + (end - start) * i / (samples - 1)
        point = Point(cx + t * ux, cy + t * uy, srid=srid)
        lonlat = point.transform(4326, clone=True)
        col, row = (int(v) for v in inverse @ (lonlat.x, lonlat.y))
        height = None
        if 0 <= row < dem.heights.shape[0] and 0 <= col < dem.heights.shape[1]:
            value = float(dem.heights[row, col])
            height = round(value, 1) if math.isfinite(value) else None
        rows.append(
            {
                "distance": round(t - start, 1),
                "elevation": height,
                "inside": parcel_m.contains(point),
            }
        )
    return rows


class TerrainModule(Module):
    name = "terrain"
    title = gettext_lazy("Terrain and slope")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        west, south, east, north = geom.extent
        dem = elevation_provider().read(
            west - DEM_MARGIN_DEG,
            south - DEM_MARGIN_DEG,
            east + DEM_MARGIN_DEG,
            north + DEM_MARGIN_DEG,
        )
        slope = slope_degrees(dem.heights, dem.transform, geom.centroid.y)
        inside = geometry_mask(
            [json.loads(geom.json)],
            out_shape=dem.heights.shape,
            transform=dem.transform,
            invert=True,
            all_touched=True,
        )
        inside &= np.isfinite(dem.heights)
        if not inside.any():
            raise ValueError("No elevation data covers the parcel")

        heights, slopes = dem.heights[inside], slope[inside]
        results = {
            "elevation_min_m": round(float(heights.min()), 1),
            "elevation_mean_m": round(float(heights.mean()), 1),
            "elevation_max_m": round(float(heights.max()), 1),
            "slope_mean_deg": round(float(slopes.mean()), 1),
            "slope_max_deg": round(float(slopes.max()), 1),
            "steep_share_pct": round(float((slopes > t.erosion_slope_deg).mean() * 100), 1),
            "cells": int(inside.sum()),
        }
        results["erosion_flag"] = results["steep_share_pct"] > 0
        mean = results["slope_mean_deg"]
        rating = (
            Rating.GREEN
            if mean < t.slope_amber_deg
            else Rating.AMBER
            if mean < t.slope_red_deg
            else Rating.RED
        )

        bounds = [0, t.slope_amber_deg, t.slope_red_deg, t.erosion_slope_deg, 90]

        def draw():
            figure = ParcelMap(geom)
            labels = [
                _("Under %(n)s°") % {"n": f"{bounds[1]:g}"},
                f"{bounds[1]:g}–{bounds[2]:g}°",
                f"{bounds[2]:g}–{bounds[3]:g}°",
                _("Over %(n)s° (erosion risk)") % {"n": f"{bounds[3]:g}"},
            ]
            figure.add_classified_raster(slope, dem.transform, bounds, style.SLOPE_CLASSES, labels)
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Slope from Copernicus DEM GLO-30 (30 m). © DLR e.V., © Airbus DS, "
                    "provided under COPERNICUS by the EU and ESA."
                )
            )

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "slope_amber_deg": t.slope_amber_deg,
                "slope_red_deg": t.slope_red_deg,
                "erosion_slope_deg": t.erosion_slope_deg,
            },
            datasets={dem.dataset: dem.version},
            maps={"main": self.render_maps(draw)},
            charts={"profile": self._profile_chart(elevation_profile(geom, dem))},
            layers=[
                classified_layer(
                    "slope",
                    lambda: _("Slope"),
                    slope,
                    dem.transform,
                    bounds,
                    style.SLOPE_CLASSES,
                    [
                        lambda: _("Under %(n)s°") % {"n": f"{bounds[1]:g}"},
                        lambda: f"{bounds[1]:g}–{bounds[2]:g}°",
                        lambda: f"{bounds[2]:g}–{bounds[3]:g}°",
                        lambda: _("Over %(n)s° (erosion risk)") % {"n": f"{bounds[3]:g}"},
                    ],
                    unit="°",
                )
            ],
        )

    def _profile_chart(self, profile):
        inside = [
            row["elevation"] for row in profile if row["inside"] and row["elevation"] is not None
        ]
        if len(inside) < 2:
            return {
                "reason": self.per_language(
                    lambda: _(
                        "No elevation profile: the parcel is too small for the 30 m elevation data."
                    )
                )
            }
        span = [row["distance"] for row in profile if row["inside"]]
        rise = max(inside) - min(inside)

        def build():
            return charts.spec(
                title=_("Elevation varies by %(m)s m across the parcel") % {"m": fmt(rise, 1)},
                source=str(_("Copernicus DEM GLO-30 (30 m), along the parcel's longest axis.")),
                data={"values": [r for r in profile if r["elevation"] is not None]},
                layer=[
                    {
                        "data": {
                            "values": [
                                {"start": min(span), "end": max(span), "label": str(_("Parcel"))}
                            ]
                        },
                        "mark": {"type": "rect", "color": "#E8E8E8"},
                        "encoding": {
                            "x": {"field": "start", "type": "quantitative"},
                            "x2": {"field": "end"},
                        },
                    },
                    {
                        "data": {
                            "values": [
                                {"middle": (min(span) + max(span)) / 2, "label": str(_("Parcel"))}
                            ]
                        },
                        "mark": {"type": "text", "baseline": "top", "dy": 4, "color": "#555555"},
                        "encoding": {
                            "x": {"field": "middle", "type": "quantitative"},
                            "y": {"value": 0},
                            "text": {"field": "label"},
                        },
                    },
                    {
                        "mark": {
                            "type": "line",
                            "color": style.SERIES["computed"],
                            "strokeWidth": 2,
                        },
                        "encoding": {
                            "x": {
                                "field": "distance",
                                "type": "quantitative",
                                "title": str(_("Distance along the parcel (m)")),
                            },
                            "y": {
                                "field": "elevation",
                                "type": "quantitative",
                                "title": str(_("Elevation (m)")),
                                "scale": {"zero": False},
                            },
                        },
                    },
                ],
            )

        return self.per_language(build)

    def key_figure(self, results):
        return _("%(s)s° average slope") % {"s": fmt(results["slope_mean_deg"], 1)}

    def finding_values(self, results):
        return {
            "slope_mean": results["slope_mean_deg"],
            "slope_max": results["slope_max_deg"],
            "elevation_min": results["elevation_min_m"],
            "elevation_max": results["elevation_max_m"],
            "steep_share": results["steep_share_pct"],
            "threshold": thresholds().erosion_slope_deg,
        }
