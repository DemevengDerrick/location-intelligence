"""Flood and water (TRD §4): water ever seen on the parcel, distance to the nearest water,
height above it, and the modelled 1-in-100-year river flood.

"Height above nearest water" is the elevation of each cell minus that of the closest mapped
water cell (straight-line nearest, on the Copernicus DEM). It is a simple, explainable stand-in
for HAND ("height above nearest drainage"), whose usual source (MERIT Hydro) is not licensed
for commercial use. The DEM is a surface model (rooftops included), so the height is
indicative: it can make a parcel amber, never red. Red needs direct evidence: water seen on the
parcel, the modelled flood zone, or a mapped wetland.
"""

import json

import numpy as np
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import reproject
from scipy.ndimage import distance_transform_edt

from .. import style
from ..config import thresholds
from ..formatting import fmt
from ..layers import classified_layer, vector_layer
from ..maps import NEIGHBOURHOOD_RADIUS_M, ParcelMap
from ..models import Rating
from ..providers import elevation_provider, water_features_provider, water_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

RETURN_PERIOD = 100
OCCURRENCE_CLASSES = [0.5, 25, 50, 75, 100.5]  # % of observations with water
OCCURRENCE_COLOURS = ["#DCEAF7", "#9ECAE1", "#4292C6", "#08519C"]
HEIGHT_CLASSES = [-1e6, 1, 3, 10, 1e6]  # metres above the nearest water
HEIGHT_COLOURS = ["#08519C", "#6BAED6", "#C6DBEF", "#F7F7F7"]
FLOOD_CLASSES = [0.001, 0.5, 1, 2, 1e6]  # modelled flood depth, metres
FLOOD_COLOURS = ["#FDD49E", "#FC8D59", "#D7301F", "#7F0000"]


def _on_grid(grid, dem):
    """Resample a lon/lat Grid onto the DEM grid (nearest neighbour)."""
    out = np.full(dem.heights.shape, np.nan, dtype="float32")
    reproject(
        grid.values,
        out,
        src_transform=grid.transform,
        src_crs="EPSG:4326",
        dst_transform=dem.transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return out


def _cell_size_m(dem, latitude):
    return (
        abs(dem.transform.e) * 110_574,
        abs(dem.transform.a) * 111_320 * np.cos(np.radians(latitude)),
    )


class FloodModule(Module):
    name = "flood"
    title = gettext_lazy("Flood and water")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        bounds = radius_bounds(geom.centroid, NEIGHBOURHOOD_RADIUS_M * 1.2)
        dem = elevation_provider().read(*bounds)
        water_data = water_provider()
        occurrence = _on_grid(water_data.occurrence(*bounds), dem)
        flood_grid = water_data.flood_depth(*bounds, return_period=RETURN_PERIOD)
        depth = _on_grid(flood_grid, dem) if flood_grid is not None else np.zeros_like(occurrence)
        depth = np.nan_to_num(depth, nan=0.0)
        features = water_features_provider().fetch(*bounds)

        shape, transform = dem.heights.shape, dem.transform
        mapped = np.zeros(shape, dtype=bool)
        shapes = [json.loads(g.json) for g in features.lines + features.areas + features.wetlands]
        if shapes:
            mapped = rasterize(
                [(s, 1) for s in shapes], out_shape=shape, transform=transform, all_touched=True
            ).astype(bool)
        water = mapped | (np.nan_to_num(occurrence) >= t.gsw_water_pct)

        inside = geometry_mask(
            [json.loads(geom.json)],
            out_shape=shape,
            transform=transform,
            invert=True,
            all_touched=True,
        )
        if not inside.any():
            raise ValueError("The parcel is smaller than one elevation cell")

        cell_y, cell_x = _cell_size_m(dem, geom.centroid.y)
        flooded = depth > 0
        flood_zone_m = None
        if flooded.any():
            flood_zone_m = float(
                distance_transform_edt(~flooded, sampling=(cell_y, cell_x))[inside].min()
            )
        heights = np.where(np.isfinite(dem.heights), dem.heights, np.nanmean(dem.heights))
        if water.any():
            distance, (rows, cols) = distance_transform_edt(
                ~water, sampling=(cell_y, cell_x), return_indices=True
            )
            height_above = heights - heights[rows, cols]
            nearest_m = float(distance[inside].min())
            height_mean = float(height_above[inside].mean())
        else:  # no mapped water within ~1.2 km
            height_above = None
            nearest_m = height_mean = None

        parcel_occurrence = np.nan_to_num(occurrence[inside])
        parcel_depth = depth[inside]
        wetland_on_parcel = any(w.intersects(geom) for w in features.wetlands)
        results = {
            "water_seen_share_pct": round(float((parcel_occurrence > 0).mean() * 100), 1),
            "water_max_occurrence_pct": round(float(parcel_occurrence.max()), 1),
            "nearest_water_m": None if nearest_m is None else round(nearest_m),
            "height_above_water_mean_m": None if height_mean is None else round(height_mean, 1),
            "flood_share_pct": round(float((parcel_depth > 0).mean() * 100), 1),
            "flood_max_depth_m": round(float(parcel_depth.max()), 2),
            "flood_zone_distance_m": None if flood_zone_m is None else round(flood_zone_m),
            "return_period": RETURN_PERIOD,
            "wetland_on_parcel": wetland_on_parcel,
            "mapped_water_features": len(shapes),
            "flood_model_covers_area": flood_grid is not None,
        }
        rating = self._rate(results, t)

        def draw_water():
            figure = ParcelMap(geom, extent="neighbourhood")
            labels = ["1–25 %", "25–50 %", "50–75 %", "75–100 %"]
            seen = np.where(np.nan_to_num(occurrence) > 0, occurrence, np.nan)
            if np.isfinite(seen).any():  # legend only when water was seen
                figure.add_classified_raster(
                    seen,
                    transform,
                    OCCURRENCE_CLASSES,
                    OCCURRENCE_COLOURS,
                    [_("Water %(range)s of the time") % {"range": label} for label in labels],
                )
            for i, line in enumerate(features.lines):
                figure.add_line(
                    line, label=_("Rivers and streams") if i == 0 else None, color="#08519C"
                )
            for i, wetland in enumerate(features.wetlands):
                figure.add(
                    wetland,
                    label=_("Wetland") if i == 0 else None,
                    facecolor="none",
                    edgecolor="#2CA25F",
                    hatch="///",
                    linewidth=0.8,
                    zorder=4,
                )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Surface water 1984–2021: EC JRC/Google (Pekel et al. 2016). "
                    "Waterways © OpenStreetMap contributors."
                )
            )

        def draw_hazard():
            figure = ParcelMap(geom, extent="neighbourhood")
            if height_above is not None:
                figure.add_classified_raster(
                    height_above,
                    transform,
                    HEIGHT_CLASSES,
                    HEIGHT_COLOURS,
                    [_("Under 1 m above water"), _("1–3 m"), _("3–10 m"), _("Over 10 m")],
                )
            if (depth > 0).any():
                figure.add_mask_outline(
                    depth > 0,
                    transform,
                    colour=style.RATING_COLOURS["red"],
                    label=_("1-in-%(rp)s-year river flood") % {"rp": RETURN_PERIOD},
                )
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Height above nearest mapped water from Copernicus DEM GLO-30. River flood "
                    "hazard: Copernicus EMS / JRC global flood maps, CC BY 4.0."
                )
            )

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "return_period": RETURN_PERIOD,
                "gsw_water_pct": t.gsw_water_pct,
                "flood_share_red_pct": t.flood_share_red_pct,
                "water_seen_red_pct": t.water_seen_red_pct,
                "height_amber_m": t.height_above_water_amber_m,
                "distance_amber_m": t.water_distance_amber_m,
                "flood_zone_amber_m": t.flood_zone_amber_m,
            },
            datasets={
                water_data.gsw_dataset: water_data.gsw_version,
                water_data.flood_dataset: water_data.flood_version,
                dem.dataset: dem.version,
                features.dataset: features.version,
            },
            maps={
                "water": self.render_maps(draw_water),
                "hazard": self.render_maps(draw_hazard),
            },
            layers=self._layers(occurrence, height_above, depth, transform, features),
        )

    @staticmethod
    def _layers(occurrence, height_above, depth, transform, features):
        ranges = ("1–25 %", "25–50 %", "50–75 %", "75–100 %")
        layers = [
            classified_layer(
                "water-seen",
                lambda: _("Water seen 1984–2021"),
                np.where(np.nan_to_num(occurrence) > 0, occurrence, np.nan),
                transform,
                OCCURRENCE_CLASSES,
                OCCURRENCE_COLOURS,
                [lambda r=r: _("Water %(range)s of the time") % {"range": r} for r in ranges],
                unit=lambda: _("% of the time"),
                decimals=0,
            ),
        ]
        if height_above is not None:
            layers.append(
                classified_layer(
                    "height",
                    lambda: _("Height above the nearest water"),
                    height_above,
                    transform,
                    HEIGHT_CLASSES,
                    HEIGHT_COLOURS,
                    [
                        lambda: _("Under 1 m above water"),
                        lambda: _("1–3 m"),
                        lambda: _("3–10 m"),
                        lambda: _("Over 10 m"),
                    ],
                    unit="m",
                    visible=False,
                    opacity=0.6,
                )
            )
        if (depth > 0).any():
            layers.append(
                classified_layer(
                    "flood",
                    lambda: _("1-in-%(rp)s-year river flood") % {"rp": RETURN_PERIOD},
                    np.where(depth > 0, depth, np.nan),
                    transform,
                    FLOOD_CLASSES,
                    FLOOD_COLOURS,
                    [
                        lambda: _("Under 0.5 m deep"),
                        lambda: _("0.5–1 m"),
                        lambda: _("1–2 m"),
                        lambda: _("Over 2 m"),
                    ],
                    unit=lambda: _("m deep"),
                )
            )
        layers += [
            vector_layer(
                "waterways",
                lambda: _("Rivers and streams"),
                [(g, {}) for g in features.lines],
                kind="line",
                color="#08519C",
                width=2,
            ),
            vector_layer(
                "water-bodies",
                lambda: _("Water bodies"),
                [(g, {}) for g in features.areas],
                kind="fill",
                color="#6BAED6",
                outline="#08519C",
                opacity=0.6,
            ),
            vector_layer(
                "wetlands",
                lambda: _("Wetland"),
                [(g, {}) for g in features.wetlands],
                kind="fill",
                color="#2CA25F",
                outline="#2CA25F",
                opacity=0.35,
            ),
        ]
        return layers

    @staticmethod
    def _rate(r, t):
        if (
            r["water_seen_share_pct"] >= t.water_seen_red_pct
            or r["flood_share_pct"] >= t.flood_share_red_pct
            or r["wetland_on_parcel"]
        ):
            return Rating.RED
        height, near, zone = (
            r["height_above_water_mean_m"],
            r["nearest_water_m"],
            r["flood_zone_distance_m"],
        )
        if (
            r["water_seen_share_pct"] > 0
            or r["flood_share_pct"] > 0
            or (height is not None and height < t.height_above_water_amber_m)
            or (near is not None and near < t.water_distance_amber_m)
            or (zone is not None and zone < t.flood_zone_amber_m)
        ):
            return Rating.AMBER
        return Rating.GREEN

    def finding_values(self, results):
        reasons = []
        if results["water_seen_share_pct"] > 0:
            reasons.append(
                _("water was seen on %(share)s %% of the parcel since 1984")
                % {"share": fmt(results["water_seen_share_pct"])}
            )
        if results["flood_share_pct"] > 0:
            reasons.append(
                _(
                    "the 1-in-%(rp)s-year river flood reaches %(share)s %% of the parcel, up to "
                    "%(depth)s m deep"
                )
                % {
                    "rp": results["return_period"],
                    "share": fmt(results["flood_share_pct"]),
                    "depth": fmt(results["flood_max_depth_m"], 1),
                }
            )
        if results["wetland_on_parcel"]:
            reasons.append(_("a wetland is mapped on the parcel"))
        t = thresholds()
        zone = results["flood_zone_distance_m"]
        if zone and zone < t.flood_zone_amber_m:  # 0 is already covered by "reaches"
            reasons.append(
                _("the 1-in-%(rp)s-year flood zone is %(d)s m away")
                % {"rp": results["return_period"], "d": fmt(zone)}
            )
        height = results["height_above_water_mean_m"]
        if height is not None and height < t.height_above_water_amber_m:
            reasons.append(_("the parcel lies %(level)s") % {"level": _level(height)})
        near = results["nearest_water_m"]
        if near is not None and near < t.water_distance_amber_m:
            reasons.append(_("a river or water body is %(d)s m away") % {"d": fmt(near)})
        if near is None:
            nearest = _("No river or water body is mapped within 1 km.")
        else:
            nearest = _(
                "The nearest river or water body is %(d)s m away; the parcel lies %(level)s."
            ) % {"d": fmt(near), "level": _level(height)}
        return {"reasons": _("; ").join(reasons), "nearest": nearest}  # French: " ; "

    def key_figure(self, results):
        if results["nearest_water_m"] is None:
            return _("No river or water body within 1 km")
        height = results["height_above_water_mean_m"]
        if height < 0.5:
            return _("%(d)s m to water · same level") % {"d": fmt(results["nearest_water_m"])}
        return _("%(d)s m to water · %(h)s m above it") % {
            "d": fmt(results["nearest_water_m"]),
            "h": fmt(height, 1),
        }


def _level(height):
    """How high the parcel sits above the nearest water, in words (never "-0.2 m above")."""
    if height < 0.5:
        return _("at about the same level as the nearest water")
    return _("about %(h)s m above the nearest water") % {"h": fmt(height, 1)}
