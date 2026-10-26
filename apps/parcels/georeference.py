"""Fit a scanned site plan onto the map from control points (FR-39).

Each control point pairs a pixel on the plan with a position on the imagery. An affine
transform (scale, rotation, shear, shift) is fitted by least squares in the local UTM zone, so
residuals are in metres: with 4 or more points they show how well the plan fits and which
point is misplaced. Three points fit exactly and leave no check.
"""

from dataclasses import dataclass

import numpy as np
from django.contrib.gis.geos import MultiPoint, Point
from django.utils.translation import gettext as _

from .geometry import utm_srid_for
from .parsers import GeometryInputError

MIN_POINTS = 3


@dataclass
class Fit:
    corners: list  # [lon, lat] of the plan's top-left, top-right, bottom-right, bottom-left
    residuals_m: list  # per control point, in the order given
    rmse_m: float | None  # None with exactly 3 points: nothing left to check against
    srid: int

    def as_json(self):
        return {
            "corners": self.corners,
            "residuals_m": self.residuals_m,
            "rmse_m": self.rmse_m,
        }


def fit_affine(points, width, height):
    """`points`: [{"pixel": [x, y], "lnglat": [lon, lat]}, ...]; pixel y grows downwards."""
    if len(points) < MIN_POINTS:
        raise GeometryInputError(
            _("Place at least %(n)s control points on both the plan and the map.")
            % {"n": MIN_POINTS}
        )
    try:
        pixels = np.array([p["pixel"] for p in points], dtype=float)
        lnglat = [(float(p["lnglat"][0]), float(p["lnglat"][1])) for p in points]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise GeometryInputError(_("The control points are incomplete.")) from exc

    srid = utm_srid_for(MultiPoint([Point(xy, srid=4326) for xy in lnglat], srid=4326).centroid)
    projected = [Point(xy, srid=4326).transform(srid, clone=True) for xy in lnglat]
    targets = np.array([(p.x, p.y) for p in projected])

    design = np.column_stack([pixels, np.ones(len(points))])
    if np.linalg.matrix_rank(design) < 3:
        raise GeometryInputError(
            _("The control points are on one line. Spread them around the plan.")
        )
    coefficients, *_unused = np.linalg.lstsq(design, targets, rcond=None)  # 3 x 2

    errors = design @ coefficients - targets
    residuals = np.hypot(errors[:, 0], errors[:, 1])
    dof = len(points) - 3
    rmse = float(np.sqrt((residuals**2).sum() / dof)) if dof > 0 else None

    frame = np.array([[0, 0, 1], [width, 0, 1], [width, height, 1], [0, height, 1]], dtype=float)
    corners = []
    for easting, northing in frame @ coefficients:
        corner = Point(easting, northing, srid=srid).transform(4326, clone=True)
        corners.append([round(corner.x, 8), round(corner.y, 8)])
    return Fit(
        corners=corners,
        residuals_m=[round(float(r), 2) for r in residuals],
        rmse_m=round(rmse, 2) if rmse is not None else None,
        srid=srid,
    )
