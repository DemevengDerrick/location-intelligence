"""Interactive map layers for the portal report (FR-19, FR-66): the same data as the static
maps, as plain dicts stored on ModuleResult.layers and drawn with MapLibre in the browser.

Two kinds:
- "image": a PNG (stored by the pipeline) placed on four lon/lat corners, with an optional
  coarse value grid so hovering can show the number under the cursor;
- "geojson": a FeatureCollection with a style and the properties to show on hover.

Titles, legend labels and units are per language ({"fr": ..., "en": ...}), like the maps.
"""

import io
import json
import math

import numpy as np
from django.utils import translation
from matplotlib.colors import BoundaryNorm, ListedColormap, to_rgba
from PIL import Image

LANGUAGES = ("fr", "en")
HOVER_GRID_MAX = 80  # cells per side kept for hover values (keeps the page light)
SIMPLIFY_DEG = 0.000005  # ≈ 0.5 m: keeps outlines exact at report scales, files small


def per_language(build):
    """{language: str(build())} with each language active (labels are lazily translated)."""
    values = {}
    for language in LANGUAGES:
        with translation.override(language):
            values[language] = str(build())
    return values


def legend_entry(colour, label, shape="fill"):
    """`label` is a callable returning the (translated) text."""
    return {"color": _hex(colour), "label": per_language(label), "shape": shape}


def _hex(colour):
    r, g, b, _a = to_rgba(colour)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def _corners(shape, transform, crs_epsg):
    """Top-left, top-right, bottom-right, bottom-left corners in lon/lat (MapLibre order)."""
    height, width = shape[:2]
    xy = [
        transform @ (0, 0),
        transform @ (width, 0),
        transform @ (width, height),
        transform @ (0, height),
    ]
    if crs_epsg != 4326:
        from rasterio.warp import transform as warp

        lons, lats = warp(f"EPSG:{crs_epsg}", "EPSG:4326", [p[0] for p in xy], [p[1] for p in xy])
        xy = list(zip(lons, lats, strict=True))
    return [[round(x, 7), round(y, 7)] for x, y in xy]


def _png(rgba):
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _hover_grid(values, decimals):
    """A coarse copy of the values (nearest cell), NaN as None, for hover readouts."""
    height, width = values.shape
    step = max(1, math.ceil(max(height, width) / HOVER_GRID_MAX))
    coarse = values[::step, ::step].astype("float64")
    return [
        [None if not math.isfinite(v) else round(float(v), decimals) for v in row] for row in coarse
    ]


def rgb_layer(
    layer_id, title, rgb, transform, crs_epsg, *, visible=True, group=None, year=None, opacity=1.0
):
    """A true-colour image (H x W x 3 floats in 0–1)."""
    rgba = np.dstack([np.clip(rgb, 0, 1), np.ones(rgb.shape[:2])])
    layer = {
        "id": layer_id,
        "type": "image",
        "title": per_language(title),
        "png": _png((rgba * 255).astype("uint8")),
        "coordinates": _corners(rgb.shape, transform, crs_epsg),
        "opacity": opacity,
        "visible": visible,
        "legend": [],
    }
    if group:
        # Share of pixels with a clear observation (unobserved ones are drawn pure white), so
        # the page can open the comparison on a clear year.
        clear = float((~np.all(rgb >= 0.999, axis=2)).mean() * 100)
        layer.update({"group": group, "year": year, "clear_pct": round(clear, 1)})
    return layer


def classified_layer(
    layer_id,
    title,
    values,
    transform,
    bounds,
    colours,
    labels,
    *,
    crs_epsg=4326,
    unit=None,
    decimals=1,
    opacity=0.75,
    visible=True,
    categories=None,
):
    """Values drawn in classes (same bounds and colours as the static map). With `unit`, hover
    shows the value; with `categories` ({value: label callable}), the class name."""
    values = np.asarray(values, dtype="float64")
    cmap = ListedColormap([to_rgba(c) for c in colours])
    norm = BoundaryNorm(bounds, cmap.N)
    rgba = cmap(norm(np.nan_to_num(values, nan=bounds[0])), bytes=True)
    rgba[..., 3] = np.where(
        np.isfinite(values) & (values >= bounds[0]) & (values <= bounds[-1]), 255, 0
    )
    layer = {
        "id": layer_id,
        "type": "image",
        "title": per_language(title),
        "png": _png(rgba),
        "coordinates": _corners(values.shape, transform, crs_epsg),
        "opacity": opacity,
        "visible": visible,
        "legend": [
            legend_entry(colour, label) for colour, label in zip(colours, labels, strict=True)
        ],
    }
    if unit is not None:
        layer["hover"] = {
            "grid": _hover_grid(values, decimals),
            "unit": per_language(unit) if callable(unit) else {lang: unit for lang in LANGUAGES},
        }
    elif categories:
        layer["hover"] = {
            "grid": _hover_grid(values, 0),
            "categories": {str(int(k)): per_language(v) for k, v in categories.items()},
        }
    return layer


def _geometry(geom):
    if geom.srid and geom.srid != 4326:
        geom = geom.transform(4326, clone=True)
    if geom.geom_type not in {"Point", "MultiPoint"}:
        simpler = geom.simplify(SIMPLIFY_DEG, preserve_topology=True)
        geom = simpler if not simpler.empty else geom
    return json.loads(geom.geojson)


def vector_layer(
    layer_id,
    title,
    features,
    *,
    kind,
    color,
    outline=None,
    opacity=0.5,
    width=1.5,
    dash=False,
    hover=(),
    legend=None,
    visible=True,
):
    """`features`: (GEOS geometry, properties) pairs. `kind`: "fill", "line" or "circle".
    `hover`: (property, label callable) pairs shown when the pointer is over a feature.
    A "color" property on a feature overrides the layer colour."""
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": _geometry(geom), "properties": dict(props or {})}
            for geom, props in features
            if geom is not None and not geom.empty
        ],
    }
    return {
        "id": layer_id,
        "type": "geojson",
        "title": per_language(title),
        "data": collection,
        "style": {
            "kind": kind,
            "color": _hex(color),
            "outline": _hex(outline) if outline else None,
            "opacity": opacity,
            "width": width,
            "dash": dash,
        },
        "hover": [{"property": prop, "label": per_language(label)} for prop, label in hover],
        "legend": legend
        if legend is not None
        else [legend_entry(color, title, "line" if kind == "line" else kind)],
        "visible": visible,
    }
