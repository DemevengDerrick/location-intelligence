"""Land cover from Sentinel-2 spectral indices: vegetation, water, and "built-up or bare
ground" (not vegetated).

At 10 m Sentinel-2 cannot reliably tell roofs and concrete from bare, cleared soil (laterite,
levelled plots), so the two are reported together. Whether there are buildings comes from
the Buildings section (footprints), not from these pixels. Index thresholds are
admin-editable (config). A 40 m × 40 m parcel is only 16 pixels: results are indicative.
"""

import json
import warnings

import numpy as np
from rasterio.features import geometry_mask

WATER, VEGETATION, OPEN = 1, 2, 3
NAMES = {WATER: "water", VEGETATION: "vegetation", OPEN: "open"}


def _index(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a - b) / (a + b)


def classify(bands, t):
    """0 = no clear observation, then WATER, VEGETATION or OPEN (built-up or bare)."""
    red, green, nir, swir = bands["red"], bands["green"], bands["nir"], bands["swir16"]
    ndvi, mndwi = _index(nir, red), _index(green, swir)
    classes = np.full(red.shape, OPEN, dtype="uint8")
    classes[ndvi > t.ndvi_vegetation] = VEGETATION
    classes[mndwi > t.mndwi_water] = WATER
    classes[~np.isfinite(red) | ~np.isfinite(nir) | ~np.isfinite(swir)] = 0
    return classes


def parcel_mask(geom, crs_epsg, transform, shape):
    projected = geom.transform(crs_epsg, clone=True)
    return geometry_mask(
        [json.loads(projected.json)],
        out_shape=shape,
        transform=transform,
        invert=True,
        all_touched=True,
    )


def shares(classes, mask):
    """Percentage of each class among clearly observed pixels in the mask, plus coverage."""
    inside = classes[mask]
    observed = inside[inside > 0]
    result = {name: 0.0 for name in NAMES.values()}
    if observed.size:
        for code, name in NAMES.items():
            result[name] = round(float((observed == code).mean() * 100), 1)
    result["coverage_pct"] = (
        round(float(observed.size / inside.size * 100), 1) if inside.size else 0.0
    )
    return result


def true_colour(bands):
    """An RGB array (0–1) with a gentle stretch, for maps and the image strip."""
    rgb = np.dstack([bands["red"], bands["green"], bands["blue"]])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        rgb = np.clip(rgb / 0.25, 0, 1) ** 0.8
    return np.nan_to_num(rgb, nan=1.0)  # unobserved pixels shown white
