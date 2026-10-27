"""Static vector maps for the PDF (FR-62, FR-63, FR-65).

Maps are drawn in metres on a local projection centred on the parcel, so the scale bar is
exact at parcel scale. Each map has a north arrow, scale bar, legend and a source line.
"""

import io
import math
import textwrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.patches import Polygon as PolygonPatch  # noqa: E402

from . import style  # noqa: E402

plt.rcParams.update({"font.family": style.FONT, "font.size": 8, "svg.fonttype": "none"})

# FR-62: three standard extents so readers compare like with like.
PARCEL_MARGIN_M = 50  # "parcel": the boundary plus 50 m
NEIGHBOURHOOD_RADIUS_M = 1_000  # "neighbourhood": 1 km around the parcel
AREA_RADIUS_M = 5_000  # "area": 5 km around the parcel
CAPTION_PT = 6
NICE_LENGTHS = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]


class LocalProjection:
    """Equirectangular projection in metres around (lon0, lat0); accurate at parcel scale."""

    def __init__(self, lon0, lat0):
        self.lon0, self.lat0 = lon0, lat0
        self.kx = 111_320 * math.cos(math.radians(lat0))
        self.ky = 110_574

    def xy(self, lon, lat):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky


def raster_extent(projection, shape, transform, crs_epsg):
    """Raster corners in map metres. UTM grids are converted through lon/lat; the slight
    rotation between UTM and the local projection is negligible at these scales."""
    height, width = shape
    west, north = transform @ (0, 0)
    east, south = transform @ (width, height)
    if crs_epsg != 4326:
        from rasterio.warp import transform as warp

        lons, lats = warp(f"EPSG:{crs_epsg}", "EPSG:4326", [west, east], [south, north])
        west, east, south, north = lons[0], lons[1], lats[0], lats[1]
    x0, y0 = projection.xy(west, south)
    x1, y1 = projection.xy(east, north)
    return x0, x1, y0, y1


def parcel_extent(projection, parcel, margin_m=None):
    """FR-62 "parcel" extent: the boundary plus 50 m, in map metres."""
    margin_m = PARCEL_MARGIN_M if margin_m is None else margin_m
    xs, ys = zip(*(projection.xy(x, y) for ring in _rings(parcel) for x, y in ring), strict=True)
    return (min(xs) - margin_m, max(xs) + margin_m, min(ys) - margin_m, max(ys) + margin_m)


def _rings(geom):
    """Exterior rings of a (Multi)Polygon as lists of (lon, lat)."""
    polygons = [geom] if geom.geom_type == "Polygon" else list(geom)
    return [list(p.exterior_ring.coords) for p in polygons]


class ParcelMap:
    """A map at a standard extent ("parcel", "neighbourhood", "area") or a radius in metres."""

    def __init__(self, parcel, extent="parcel"):
        centre = parcel.centroid
        self.projection = LocalProjection(centre.x, centre.y)
        if extent == "parcel":
            self.extent = parcel_extent(self.projection, parcel)
        elif isinstance(extent, int | float):
            self.extent = (-extent, extent, -extent, extent)
        else:
            r = NEIGHBOURHOOD_RADIUS_M if extent == "neighbourhood" else AREA_RADIUS_M
            self.extent = (-r, r, -r, r)
        self.fig, self.ax = plt.subplots(figsize=style.MAP_SIZE_IN)
        self.ax.set_facecolor("#F5F5F2")
        self.legend = []

    def add(self, geom, label=None, **patch_style):
        for ring in _rings(geom):
            points = [self.projection.xy(x, y) for x, y in ring]
            self.ax.add_patch(PolygonPatch(points, closed=True, **patch_style))
        if label:
            self._legend_entry(label, patch_style)

    def add_parcel(self, parcel, label):
        self.add(parcel, **style.PARCEL_HALO)
        self.add(parcel, label=label, **style.PARCEL)

    def add_line(self, line, label=None, color="#08519C", linewidth=1.4):
        points = [self.projection.xy(x, y) for x, y in line.coords]
        xs, ys = zip(*points, strict=True)
        self.ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=6)
        if label:
            self.legend.append(Line2D([0], [0], color=color, linewidth=linewidth, label=label))

    def add_points(self, points, label, colour, marker="o", size=36):
        """Point symbols (e.g. services), lon/lat pairs; only drawn if any falls on the map."""
        x0, x1, y0, y1 = self.extent
        xy = [self.projection.xy(lon, lat) for lon, lat in points]
        xy = [(x, y) for x, y in xy if x0 <= x <= x1 and y0 <= y <= y1]
        if not xy:
            return
        xs, ys = zip(*xy, strict=True)
        self.ax.scatter(
            xs, ys, s=size, c=colour, marker=marker, edgecolors="white", linewidths=0.8, zorder=8
        )
        self.legend.append(
            Line2D(
                [0],
                [0],
                marker=marker,
                color="none",
                markerfacecolor=colour,
                markeredgecolor="white",
                markersize=7,
                label=label,
            )  # fmt: skip
        )

    def add_mask_outline(self, mask, transform, colour, label, crs_epsg=4326):
        """The outline of a boolean raster (e.g. a flood zone), drawn as a contour."""
        x0, x1, y0, y1 = raster_extent(self.projection, mask.shape, transform, crs_epsg)
        self.ax.contour(
            mask.astype(float),
            levels=[0.5],
            extent=(x0, x1, y1, y0),
            colors=[colour],
            linewidths=1.6,
            zorder=7,
        )
        self.legend.append(Line2D([0], [0], color=colour, linewidth=1.6, label=label))

    def add_rgb(self, rgb, transform, crs_epsg):
        self.ax.imshow(
            rgb, extent=raster_extent(self.projection, rgb.shape[:2], transform, crs_epsg), zorder=1
        )

    def add_classified_raster(self, values, transform, bounds, colours, labels, crs_epsg=4326):
        """A raster drawn in classes with a legend (lon/lat grid unless `crs_epsg` says not)."""
        x0, x1, y0, y1 = raster_extent(self.projection, values.shape, transform, crs_epsg)
        cmap = ListedColormap(colours)
        self.ax.imshow(
            values,
            extent=(x0, x1, y0, y1),
            cmap=cmap,
            norm=BoundaryNorm(bounds, cmap.N),
            interpolation="nearest",
            zorder=1,
        )
        for colour, label in zip(colours, labels, strict=True):
            self.legend.append(Patch(facecolor=colour, edgecolor="#777777", label=label))

    def _legend_entry(self, label, patch_style):
        face = patch_style.get("facecolor", "none")
        if patch_style.get("hatch"):
            self.legend.append(
                Patch(
                    facecolor="none",
                    edgecolor=patch_style.get("edgecolor", "#000"),
                    hatch=patch_style["hatch"],
                    label=label,
                )
            )
        elif face == "none":
            self.legend.append(
                Line2D(
                    [0],
                    [0],
                    color=patch_style.get("edgecolor", "#000"),
                    linestyle=patch_style.get("linestyle", "-"),
                    linewidth=patch_style.get("linewidth", 1),
                    label=label,
                )
            )
        else:
            self.legend.append(
                Patch(facecolor=face, edgecolor=patch_style.get("edgecolor", face), label=label)
            )

    def to_svg(self, source):
        ax = self.ax
        ax.set_xlim(self.extent[0], self.extent[1])
        ax.set_ylim(self.extent[2], self.extent[3])
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        self._north_arrow()
        self._scale_bar()
        if self.legend:
            legend = ax.legend(handles=self.legend, loc="upper left", fontsize=7, framealpha=0.9)
            legend.set_zorder(30)  # above roads and points
        _caption(ax, source)
        buffer = io.BytesIO()
        self.fig.savefig(buffer, format="svg", bbox_inches="tight", pad_inches=0.15)
        plt.close(self.fig)
        return buffer.getvalue()

    def _north_arrow(self):
        self.ax.annotate(
            "N",
            xy=(0.95, 0.95),
            xytext=(0.95, 0.82),
            xycoords="axes fraction",
            ha="center",
            va="center",
            fontsize=10,
            fontweight="bold",
            arrowprops={"arrowstyle": "-|>", "color": "#000000", "lw": 1.5},
        )

    def _scale_bar(self):
        xmin, xmax, ymin, ymax = self.extent
        target = (xmax - xmin) / 4
        length = max((n for n in NICE_LENGTHS if n <= target), default=NICE_LENGTHS[0])
        x0, y0 = xmin + (xmax - xmin) * 0.05, ymin + (ymax - ymin) * 0.06
        self.ax.plot(
            [x0, x0 + length],
            [y0, y0],
            color="#000000",
            linewidth=3,
            solid_capstyle="butt",
            zorder=20,
        )
        self.ax.text(
            x0 + length / 2,
            y0 + (ymax - ymin) * 0.025,
            f"{length // 1000} km" if length >= 1000 and length % 1000 == 0 else f"{length} m",
            ha="center",
            fontsize=7,
            zorder=20,
        )


def _caption(ax, source):
    """The source line under the map, wrapped to the map's width: one long line would widen
    the saved image and shrink the map on the page."""
    ax.figure.canvas.draw()  # the axes' final size, after the equal aspect is applied
    width_pt = ax.get_window_extent().width * 72 / ax.figure.dpi
    chars = max(40, int(width_pt / (CAPTION_PT * 0.55)))
    ax.text(
        0,
        -0.015,
        textwrap.fill(source, chars),
        transform=ax.transAxes,
        fontsize=CAPTION_PT,
        color="#444444",
        ha="left",
        va="top",
    )


def image_strip(frames, parcel, source, columns=5):
    """Small multiples (FR table "Image strip"): one image per year, same extent and scale.

    `frames` is a list of (label, rgb, transform, crs_epsg).
    """
    rows = max(1, math.ceil(len(frames) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(style.MAP_SIZE_IN[0], 1.45 * rows + 0.3))
    axes = list(axes.flat) if hasattr(axes, "flat") else [axes]
    centre = parcel.centroid
    projection = LocalProjection(centre.x, centre.y)
    extent = parcel_extent(projection, parcel)
    for ax, (label, rgb, transform, crs_epsg) in zip(axes, frames, strict=False):
        ax.imshow(rgb, extent=raster_extent(projection, rgb.shape[:2], transform, crs_epsg))
        for ring in _rings(parcel):
            points = [projection.xy(x, y) for x, y in ring]
            ax.add_patch(PolygonPatch(points, closed=True, **style.PARCEL_HALO))
            ax.add_patch(PolygonPatch(points, closed=True, **style.PARCEL))
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
        ax.set_aspect("equal")
        ax.set_title(label, fontsize=8)
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
        if not ax.images:
            ax.axis("off")
    fig.text(0.01, 0.005, source, fontsize=6, color="#444444", ha="left", va="bottom")
    buffer = io.BytesIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return buffer.getvalue()
