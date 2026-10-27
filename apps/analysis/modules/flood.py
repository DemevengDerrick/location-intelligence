"""Flood and water (TRD §4): the modelled 1-in-100-year river flood overlaid on the parcel,
and water ever seen on it.

The flood hazard is the Copernicus EMS / JRC global river flood map (~90 m): depth of the
1-in-100-year flood of rivers with large catchments. It does not model flooding from heavy
rain, blocked drains or the sea, which the finding says. Water seen on the parcel since 1984
(JRC Global Surface Water) and mapped wetlands are direct evidence. Rivers, streams and water
bodies from OpenStreetMap are shown for context and give the distance to the nearest water.
"""

import json
from dataclasses import replace

import numpy as np
from django.contrib.gis.geos import Polygon
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, rasterize
from rasterio.warp import reproject
from scipy.ndimage import distance_transform_edt

from ..config import thresholds
from ..formatting import fmt
from ..layers import classified_layer, vector_layer
from ..maps import NEIGHBOURHOOD_RADIUS_M, ParcelMap
from ..models import Rating
from ..providers import water_features_provider, water_provider
from .base import Module, ModuleOutput
from .imagery import radius_bounds

RETURN_PERIOD = 100
OCCURRENCE_CLASSES = [0.5, 25, 50, 75, 100.5]  # % of observations with water
OCCURRENCE_COLOURS = ["#DCEAF7", "#9ECAE1", "#4292C6", "#08519C"]
FLOOD_CLASSES = [0.001, 0.5, 1, 2, 1e6]  # modelled flood depth, metres
FLOOD_COLOURS = ["#FDD49E", "#FC8D59", "#D7301F", "#7F0000"]
WATER_LINE, WATER_FILL, WETLAND = "#08519C", "#6BAED6", "#2CA25F"


def _on_grid(grid, base):
    """Resample a lon/lat Grid onto another one (nearest neighbour)."""
    out = np.full(base.values.shape, np.nan, dtype="float32")
    reproject(
        grid.values,
        out,
        src_transform=grid.transform,
        src_crs="EPSG:4326",
        dst_transform=base.transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return out


def _clipped(geoms, window, dims):
    """The parts of `geoms` inside the analysis window, as simple lines (`dims` 1) or polygons
    (2). The local OSM copy returns whole rivers and estuaries, tens of kilometres long, which
    would otherwise stretch the interactive map far beyond the parcel."""
    parts = []
    for geom in geoms:
        if not geom.intersects(window):
            continue
        cut = geom.intersection(window)
        for part in cut if cut.geom_type.startswith(("Multi", "GeometryCollection")) else [cut]:
            if part.dims == dims and not part.empty:
                parts.append(part)
    return parts


def _cell_size_m(transform, latitude):
    return (
        abs(transform.e) * 110_574,
        abs(transform.a) * 111_320 * np.cos(np.radians(latitude)),
    )


def _depth_labels():
    return [_("Under 0.5 m deep"), _("0.5–1 m"), _("1–2 m"), _("Over 2 m")]


class FloodModule(Module):
    name = "flood"
    title = gettext_lazy("Flood and water")

    def run(self, parcel):
        t = thresholds()
        geom = parcel.geometry
        bounds = radius_bounds(geom.centroid, NEIGHBOURHOOD_RADIUS_M * 1.2)
        water_data = water_provider()
        base = water_data.occurrence(*bounds)  # ~30 m: the grid everything is measured on
        occurrence = base.values
        flood_grid = water_data.flood_depth(*bounds, return_period=RETURN_PERIOD)
        depth = _on_grid(flood_grid, base) if flood_grid is not None else np.zeros_like(occurrence)
        depth = np.nan_to_num(depth, nan=0.0)
        features = water_features_provider().fetch(*bounds)
        window = Polygon.from_bbox(bounds)
        window.srid = 4326
        features = replace(
            features,
            lines=_clipped(features.lines, window, 1),
            areas=_clipped(features.areas, window, 2),
            wetlands=_clipped(features.wetlands, window, 2),
        )

        shape, transform = occurrence.shape, base.transform
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
            raise ValueError("The parcel is outside the surface-water grid")

        cell_y, cell_x = _cell_size_m(transform, geom.centroid.y)
        flooded = depth > 0
        flood_zone_m = None
        if flooded.any():
            flood_zone_m = float(
                distance_transform_edt(~flooded, sampling=(cell_y, cell_x))[inside].min()
            )
        nearest_m = None
        if water.any():
            nearest_m = float(
                distance_transform_edt(~water, sampling=(cell_y, cell_x))[inside].min()
            )

        parcel_occurrence = np.nan_to_num(occurrence[inside])
        parcel_depth = depth[inside]
        wetland_on_parcel = any(w.intersects(geom) for w in features.wetlands)
        results = {
            "flood_share_pct": round(float((parcel_depth > 0).mean() * 100), 1),
            "flood_max_depth_m": round(float(parcel_depth.max()), 2),
            "flood_zone_distance_m": None if flood_zone_m is None else round(flood_zone_m),
            "return_period": RETURN_PERIOD,
            "flood_model_covers_area": flood_grid is not None,
            "water_seen_share_pct": round(float((parcel_occurrence > 0).mean() * 100), 1),
            "water_max_occurrence_pct": round(float(parcel_occurrence.max()), 1),
            "nearest_water_m": None if nearest_m is None else round(nearest_m),
            "wetland_on_parcel": wetland_on_parcel,
            "mapped_water_features": len(shapes),
        }
        rating = self._rate(results, t)

        def add_water_features(figure):
            for i, line in enumerate(features.lines):
                figure.add_line(
                    line, label=_("Rivers and streams") if i == 0 else None, color=WATER_LINE
                )
            for i, area in enumerate(features.areas):
                figure.add(
                    area,
                    label=_("Water bodies") if i == 0 else None,
                    facecolor=WATER_FILL,
                    edgecolor=WATER_LINE,
                    linewidth=0.6,
                    zorder=3,
                )
            for i, wetland in enumerate(features.wetlands):
                figure.add(
                    wetland,
                    label=_("Wetland") if i == 0 else None,
                    facecolor="none",
                    edgecolor=WETLAND,
                    hatch="///",
                    linewidth=0.8,
                    zorder=4,
                )

        def draw_hazard():
            figure = ParcelMap(geom, extent="neighbourhood")
            if flooded.any():
                figure.add_classified_raster(
                    np.where(flooded, depth, np.nan),
                    transform,
                    FLOOD_CLASSES,
                    FLOOD_COLOURS,
                    [
                        _("1-in-%(rp)s-year flood: %(depth)s") % {"rp": RETURN_PERIOD, "depth": d}
                        for d in _depth_labels()
                    ],
                )
            add_water_features(figure)
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "1-in-100-year river flood depth: Copernicus EMS / JRC global flood hazard "
                    "maps, CC BY 4.0. Waterways © OpenStreetMap contributors."
                )
            )

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
            add_water_features(figure)
            figure.add_parcel(geom, _("Parcel boundary"))
            return figure.to_svg(
                _(
                    "Surface water 1984–2021: EC JRC/Google (Pekel et al. 2016). "
                    "Waterways © OpenStreetMap contributors."
                )
            )

        return ModuleOutput(
            rating=rating,
            results=results,
            parameters={
                "return_period": RETURN_PERIOD,
                "gsw_water_pct": t.gsw_water_pct,
                "flood_share_red_pct": t.flood_share_red_pct,
                "flood_depth_red_m": t.flood_depth_red_m,
                "flood_zone_amber_m": t.flood_zone_amber_m,
                "water_seen_red_pct": t.water_seen_red_pct,
            },
            datasets={
                water_data.flood_dataset: water_data.flood_version,
                water_data.gsw_dataset: water_data.gsw_version,
                features.dataset: features.version,
            },
            maps={  # stored as jsonb, which orders keys by length then name: "flood" first
                "flood": self.render_maps(draw_hazard),
                "water": self.render_maps(draw_water),
            },
            layers=self._layers(occurrence, depth, transform, features),
        )

    @staticmethod
    def _layers(occurrence, depth, transform, features):
        ranges = ("1–25 %", "25–50 %", "50–75 %", "75–100 %")
        layers = []
        if (depth > 0).any():
            layers.append(
                classified_layer(
                    "flood",
                    lambda: _("1-in-%(rp)s-year river flood") % {"rp": RETURN_PERIOD},
                    np.where(depth > 0, depth, np.nan),
                    transform,
                    FLOOD_CLASSES,
                    FLOOD_COLOURS,
                    [lambda i=i: _depth_labels()[i] for i in range(4)],
                    unit=lambda: _("m deep"),
                    opacity=0.7,
                )
            )
        layers += [
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
                visible=not (depth > 0).any(),
            ),
            vector_layer(
                "waterways",
                lambda: _("Rivers and streams"),
                [(g, {}) for g in features.lines],
                kind="line",
                color=WATER_LINE,
                width=2,
            ),
            vector_layer(
                "water-bodies",
                lambda: _("Water bodies"),
                [(g, {}) for g in features.areas],
                kind="fill",
                color=WATER_FILL,
                outline=WATER_LINE,
                opacity=0.6,
            ),
            vector_layer(
                "wetlands",
                lambda: _("Wetland"),
                [(g, {}) for g in features.wetlands],
                kind="fill",
                color=WETLAND,
                outline=WETLAND,
                opacity=0.35,
            ),
        ]
        return layers

    @staticmethod
    def _rate(r, t):
        in_zone = r["flood_share_pct"] > 0
        if (
            r["flood_share_pct"] >= t.flood_share_red_pct
            or (in_zone and r["flood_max_depth_m"] >= t.flood_depth_red_m)
            or r["water_seen_share_pct"] >= t.water_seen_red_pct
            or r["wetland_on_parcel"]
        ):
            return Rating.RED
        zone = r["flood_zone_distance_m"]
        if (
            in_zone
            or r["water_seen_share_pct"] > 0
            or (zone is not None and zone < t.flood_zone_amber_m)
        ):
            return Rating.AMBER
        return Rating.GREEN

    def finding_values(self, results):
        reasons = []
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
        if results["water_seen_share_pct"] > 0:
            reasons.append(
                _("water was seen on %(share)s %% of the parcel since 1984")
                % {"share": fmt(results["water_seen_share_pct"])}
            )
        if results["wetland_on_parcel"]:
            reasons.append(_("a wetland is mapped on the parcel"))
        zone = results["flood_zone_distance_m"]
        if zone and zone < thresholds().flood_zone_amber_m:  # 0 is already covered by "reaches"
            reasons.append(
                _("the 1-in-%(rp)s-year flood zone is %(d)s m away")
                % {"rp": results["return_period"], "d": fmt(zone)}
            )
        near = results["nearest_water_m"]
        if near is None:
            nearest = _("No river or water body is mapped within 1 km.")
        else:
            nearest = _("The nearest river or water body is %(d)s m away.") % {"d": fmt(near)}
        return {"reasons": _("; ").join(reasons), "nearest": nearest}  # French: " ; "

    def key_figure(self, results):
        if results["flood_share_pct"] > 0:
            return _("%(share)s %% in the 100-year flood zone · up to %(depth)s m") % {
                "share": fmt(results["flood_share_pct"]),
                "depth": fmt(results["flood_max_depth_m"], 1),
            }
        zone = results["flood_zone_distance_m"]
        if zone is None:
            return _("No 100-year flood zone within 1 km")
        return _("100-year flood zone %(d)s m away") % {"d": fmt(zone)}
