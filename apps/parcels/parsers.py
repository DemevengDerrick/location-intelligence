"""Turn an uploaded coordinates file into a WGS84 (Multi)Polygon (FR-7, FR-8).

Supported: GeoJSON, KML, KMZ, GPX, zipped Shapefile (read with GDAL) and CSV/TXT with
longitude/latitude or UTM 32N/33N easting/northing columns (parsed here, so decimal commas
and semicolon separators from French spreadsheets work).
"""

import csv
import io
import tempfile
import zipfile
from pathlib import Path

from django.contrib.gis.gdal import DataSource, GDALException
from django.contrib.gis.geos import GEOSGeometry, LinearRing, MultiPolygon, Polygon
from django.utils.translation import gettext as _

from .geometry import UTM_32N, UTM_33N

MAX_FILE_BYTES = 10 * 1024 * 1024
GDAL_SUFFIXES = {".geojson", ".json", ".kml", ".kmz", ".gpx", ".zip"}
CSV_SUFFIXES = {".csv", ".txt"}
SUPPORTED_SUFFIXES = GDAL_SUFFIXES | CSV_SUFFIXES

WGS84 = "wgs84"
CRS_CHOICES = {WGS84: 4326, "utm32n": UTM_32N, "utm33n": UTM_33N}

_LON = {"lon", "long", "longitude", "lng", "x_wgs84"}
_LAT = {"lat", "latitude", "y_wgs84"}
_EAST = {"x", "e", "east", "easting", "est"}
_NORTH = {"y", "n", "north", "northing", "nord"}


class GeometryInputError(ValueError):
    """A problem with the customer's input, with a message safe to show them."""


def parse_geometry_file(uploaded, crs=WGS84) -> GEOSGeometry:
    """Return a WGS84 Polygon or MultiPolygon. `crs` is only used for CSV coordinates."""
    name = uploaded.name or ""
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise GeometryInputError(
            _("Unsupported file type. Use KML, KMZ, GeoJSON, GPX, a zipped shapefile or CSV.")
        )
    if uploaded.size > MAX_FILE_BYTES:
        raise GeometryInputError(_("The coordinates file is too large (10 MB maximum)."))
    data = uploaded.read()
    if suffix in CSV_SUFFIXES:
        return _parse_csv(data, crs)
    with tempfile.TemporaryDirectory() as tmp:
        path = _materialise(Path(tmp), suffix, data)
        return _parse_with_gdal(path)


# --- GDAL formats -----------------------------------------------------------------------


def _materialise(tmp: Path, suffix: str, data: bytes) -> Path:
    if suffix not in {".kmz", ".zip"}:
        path = tmp / f"upload{suffix}"
        path.write_bytes(data)
        return path
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise GeometryInputError(_("The archive could not be opened.")) from exc
    wanted = ".kml" if suffix == ".kmz" else ".shp"
    members = [m for m in archive.namelist() if m.lower().endswith(wanted) and "__MACOSX" not in m]
    if not members:
        raise GeometryInputError(
            _("No KML file found in the KMZ.")
            if suffix == ".kmz"
            else _("No .shp file found in the zip.")
        )
    for member in archive.namelist():
        target = (tmp / member).resolve()
        if not str(target).startswith(str(tmp.resolve())):
            raise GeometryInputError(_("The archive could not be opened."))
        if not member.endswith("/"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))
    return tmp / members[0]


def _parse_with_gdal(path: Path) -> GEOSGeometry:
    try:
        source = DataSource(str(path))
    except GDALException as exc:
        raise GeometryInputError(_("The file could not be read.")) from exc

    polygons, lines, points = [], [], []
    for layer in source:
        for feature in layer:
            geom = feature.geom
            # Files without a declared CRS are taken as WGS84; the inside-Cameroon check
            # catches projected coordinates that slipped through.
            if geom.srs is not None and geom.srs.srid != 4326:
                geom.transform(4326)
            geom.set_3d(False)
            _collect(GEOSGeometry(geom.wkb, srid=4326), polygons, lines, points)

    return _assemble(polygons, lines, points)


def _collect(geom, polygons, lines, points):
    kind = geom.geom_type
    if kind in ("MultiPolygon", "MultiLineString", "MultiPoint", "GeometryCollection"):
        for part in geom:
            part.srid = 4326
            _collect(part, polygons, lines, points)
    elif kind == "Polygon":
        polygons.append(geom)
    elif kind in ("LineString", "LinearRing"):
        lines.append(geom)
    elif kind == "Point":
        points.append(geom)


def _assemble(polygons, lines, points) -> GEOSGeometry:
    if polygons:
        return MultiPolygon(*polygons, srid=4326) if len(polygons) > 1 else polygons[0]
    if lines:
        # A traced boundary (GPX track, KML line): close it into a polygon.
        longest = max(lines, key=lambda line: line.num_points)
        return _ring_polygon(list(longest.coords))
    if points:
        return _ring_polygon([p.coords for p in points])
    raise GeometryInputError(_("No coordinates were found in the file."))


def _ring_polygon(coords) -> Polygon:
    coords = [(round(x, 9), round(y, 9)) for x, y, *_ in coords]
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    if len(set(coords)) < 3:
        raise GeometryInputError(_("At least 3 corner points are needed to describe a parcel."))
    return Polygon(LinearRing(coords + [coords[0]]), srid=4326)


# --- CSV ---------------------------------------------------------------------------------


def _parse_csv(data: bytes, crs: str) -> GEOSGeometry:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [
        row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise GeometryInputError(_("The CSV file is empty."))

    header = [cell.strip().lower() for cell in rows[0]]
    x_col, y_col, projected = _coordinate_columns(header)
    body = rows[1:] if x_col is not None else rows
    if x_col is None:  # no header: assume the first two columns are x, y
        x_col, y_col, projected = 0, 1, None

    coords = []
    for line_no, row in enumerate(body, start=2 if body is not rows else 1):
        try:
            x, y = _number(row[x_col]), _number(row[y_col])
        except (IndexError, ValueError) as exc:
            raise GeometryInputError(
                _("Line %(line)s does not contain valid coordinates.") % {"line": line_no}
            ) from exc
        coords.append((x, y))

    looks_projected = all(abs(x) > 180 or abs(y) > 90 for x, y in coords)
    if projected is None:
        projected = looks_projected
    if projected:
        srid = CRS_CHOICES.get(crs)
        if srid in (None, 4326):
            raise GeometryInputError(
                _("These look like UTM coordinates. Choose UTM zone 32N or 33N and upload again.")
            )
    else:
        srid = 4326
        if looks_projected:
            raise GeometryInputError(_("Longitude and latitude values are out of range."))

    polygon = _ring_polygon(coords)
    polygon.srid = srid
    return polygon.transform(4326, clone=True) if srid != 4326 else polygon


def _coordinate_columns(header):
    """(x index, y index, projected?) from a header row, or (None, None, None)."""

    def find(names):
        return next((i for i, h in enumerate(header) if h in names), None)

    lon, lat = find(_LON), find(_LAT)
    if lon is not None and lat is not None:
        return lon, lat, False
    east, north = find(_EAST), find(_NORTH)
    if east is not None and north is not None:
        return east, north, None  # x/y may be degrees or metres: decided from the values
    return None, None, None


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GeometryInputError(_("The file could not be read."))


def _number(cell: str) -> float:
    return float(cell.strip().replace(" ", "").replace(" ", "").replace(",", "."))
