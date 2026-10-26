import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import translation

from apps.parcels.geometry import area_m2
from apps.parcels.parsers import GeometryInputError, parse_geometry_file
from apps.parcels.testing import DOUALA, GAROUA, square_corners_utm, square_m

SQUARE = square_m(*DOUALA, 100)  # 1 ha
RING = list(SQUARE[0][0])  # closed ring of (lon, lat)


@pytest.fixture(autouse=True)
def english():
    with translation.override("en"):
        yield


def upload(name, content):
    if isinstance(content, str):
        content = content.encode()
    return SimpleUploadedFile(name, content)


def assert_douala_hectare(geom):
    assert geom.srid == 4326
    assert geom.geom_type in ("Polygon", "MultiPolygon")
    assert area_m2(geom) == pytest.approx(10_000, rel=0.01)


def kml_document():
    coords = " ".join(f"{x},{y},0" for x, y in RING)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>Lot 12</name>
<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing>
</outerBoundaryIs></Polygon></Placemark></Document></kml>"""


def test_geojson_feature_collection():
    data = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": json.loads(SQUARE.geojson)}],
    }
    assert_douala_hectare(parse_geometry_file(upload("parcel.geojson", json.dumps(data))))


def test_kml_polygon_with_altitude():
    assert_douala_hectare(parse_geometry_file(upload("parcel.kml", kml_document())))


def test_kmz_archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("doc.kml", kml_document())
    assert_douala_hectare(parse_geometry_file(upload("parcel.kmz", buffer.getvalue())))


def test_gpx_track_is_closed_into_a_polygon():
    points = "".join(f'<trkpt lat="{y}" lon="{x}"></trkpt>' for x, y in RING)
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1" creator="test" '
        'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        f"{points}</trkseg></trk></gpx>"
    )
    assert_douala_hectare(parse_geometry_file(upload("walk.gpx", gpx)))


def test_gpx_waypoints_at_corners():
    wpts = "".join(
        f'<wpt lat="{y}" lon="{x}"><name>B{i}</name></wpt>' for i, (x, y) in enumerate(RING[:-1])
    )
    gpx = (
        '<?xml version="1.0"?><gpx version="1.1" creator="test" '
        f'xmlns="http://www.topografix.com/GPX/1/1">{wpts}</gpx>'
    )
    assert_douala_hectare(parse_geometry_file(upload("corners.gpx", gpx)))


def test_zipped_shapefile_in_utm_is_reprojected(tmp_path):
    utm = SQUARE.transform(32632, clone=True)
    source = tmp_path / "parcel.geojson"
    source.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:32632"}},
                "features": [
                    {"type": "Feature", "properties": {}, "geometry": json.loads(utm.geojson)}
                ],
            }
        )
    )
    subprocess.run(
        ["ogr2ogr", "-f", "ESRI Shapefile", str(tmp_path / "parcel.shp"), str(source)], check=True
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for part in tmp_path.glob("parcel.*"):
            if part.suffix != ".geojson":
                archive.write(part, f"plan/{part.name}")
    geom = parse_geometry_file(upload("parcel.zip", buffer.getvalue()))
    assert_douala_hectare(geom)
    assert geom.centroid.x == pytest.approx(DOUALA[0], abs=1e-4)
    assert geom.centroid.y == pytest.approx(DOUALA[1], abs=1e-4)


def test_csv_with_lat_lon_header():
    rows = ["name,latitude,longitude"] + [f"B{i},{y},{x}" for i, (x, y) in enumerate(RING[:-1])]
    assert_douala_hectare(parse_geometry_file(upload("corners.csv", "\n".join(rows))))


def test_french_csv_with_semicolons_and_decimal_commas():
    rows = ["Borne;Longitude;Latitude"] + [
        f"B{i};{x:.7f};{y:.7f}".replace(".", ",") for i, (x, y) in enumerate(RING[:-1])
    ]
    assert_douala_hectare(parse_geometry_file(upload("bornes.csv", "\n".join(rows))))


def test_csv_in_utm_zone_32n():
    rows = ["X;Y"] + [f"{x:.2f};{y:.2f}" for x, y in square_corners_utm(*DOUALA, 100)]
    geom = parse_geometry_file(upload("bornes.csv", "\n".join(rows)), crs="utm32n")
    assert_douala_hectare(geom)


def test_csv_in_utm_zone_33n():
    rows = ["easting,northing"] + [f"{x},{y}" for x, y in square_corners_utm(*GAROUA, 100)]
    geom = parse_geometry_file(upload("corners.csv", "\n".join(rows)), crs="utm33n")
    assert area_m2(geom) == pytest.approx(10_000, rel=0.01)
    assert geom.centroid.x == pytest.approx(GAROUA[0], abs=1e-4)


def test_csv_utm_without_zone_asks_for_it():
    rows = ["X,Y"] + [f"{x},{y}" for x, y in square_corners_utm(*DOUALA, 100)]
    with pytest.raises(GeometryInputError, match="UTM"):
        parse_geometry_file(upload("corners.csv", "\n".join(rows)))


def test_csv_without_header_is_read_as_lon_lat():
    rows = [f"{x},{y}" for x, y in RING[:-1]]
    assert_douala_hectare(parse_geometry_file(upload("corners.txt", "\n".join(rows))))


@pytest.mark.parametrize(
    "name, content, message",
    [
        ("plan.docx", b"PK..", "Unsupported file type"),
        ("corners.csv", "lat,lon\n4.05,9.70\n4.06,9.71\n", "At least 3 corner points"),
        ("corners.csv", "lat,lon\n4.05,abc\n", "Line 2"),
        ("corners.csv", "", "empty"),
        ("parcel.kmz", b"not a zip", "could not be opened"),
        ("parcel.zip", b"not a zip", "could not be opened"),
        ("parcel.geojson", "{not json", "could not be read"),
    ],
)
def test_bad_files_give_clear_errors(name, content, message):
    with pytest.raises(GeometryInputError, match=message):
        parse_geometry_file(upload(name, content))


def test_zip_without_shapefile():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    with pytest.raises(GeometryInputError, match=r"No \.shp file"):
        parse_geometry_file(upload("parcel.zip", buffer.getvalue()))


def test_zip_slip_paths_are_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../evil.shp", "x")
    with pytest.raises(GeometryInputError):
        parse_geometry_file(upload("parcel.zip", buffer.getvalue()))
    assert not Path("/evil.shp").exists()
