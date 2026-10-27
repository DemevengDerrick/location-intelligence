import csv
import gzip

import pytest
from django.contrib.gis.geos import Polygon

from apps.buildings import loader
from apps.buildings.models import Building, BuildingRelease, ReleaseStatus
from apps.buildings.testing import make_release
from apps.parcels.testing import DOUALA, square_m

OUTLINE = Polygon.from_bbox((8.5, 2.0, 16.0, 13.0))
OUTLINE.srid = 4326


def tile(tmp_path, rows):
    path = tmp_path / "105_buildings.csv.gz"
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["latitude", "longitude", "area_in_meters", "confidence", "geometry", "full_plus_code"]
        )
        for lon, lat, confidence in rows:
            d = 0.00005
            wkt = (
                f"POLYGON(({lon - d} {lat - d}, {lon + d} {lat - d}, {lon + d} {lat + d}, "
                f"{lon - d} {lat + d}, {lon - d} {lat - d}))"
            )
            writer.writerow([lat, lon, 120.5, confidence, wkt, "6FMHRJM5+MGCM"])
    return path


def test_only_buildings_centred_in_cameroon_are_read(tmp_path):
    path = tile(tmp_path, [(*DOUALA, 0.9), (7.5, 9.0, 0.95), (9.0, 4.0, 0.66)])  # 2nd: Nigeria
    rows = list(loader.read_rows([path], OUTLINE, log=lambda _m: None))
    assert [r[2] for r in rows] == [0.9, 0.66]  # all scores kept: the cut-off is a threshold
    assert rows[0][0].startswith("SRID=4326;POLYGON((")


@pytest.mark.django_db(transaction=True)
def test_a_load_replaces_the_active_release(tmp_path):
    old = make_release([square_m(*DOUALA, 10)])
    path = tile(tmp_path, [(*DOUALA, 0.9), (9.71, 4.06, 0.8)])

    new = loader.load([path], outline=OUTLINE, log=lambda _m: None)

    assert new.status == ReleaseStatus.ACTIVE and BuildingRelease.active() == new
    assert new.count == 2 and new.version == "v3"
    old.refresh_from_db()
    assert old.status == ReleaseStatus.RETIRED
    assert not Building.objects.filter(release=old).exists()
    building = Building.objects.filter(release=new).first()
    assert building.geom.valid and building.area_m2 == 120.5


def test_tiles_are_downloaded_once(tmp_path, settings, monkeypatch):
    settings.BUILDINGS_DATA_DIR = str(tmp_path)
    fetched = []
    monkeypatch.setattr(loader, "download_file", lambda url, path: fetched.append(url))
    (tmp_path / "105_buildings.csv.gz").write_bytes(b"")
    paths = loader.download(tiles=("105", "107"), log=lambda _m: None)
    assert [p.name for p in paths] == ["105_buildings.csv.gz", "107_buildings.csv.gz"]
    assert fetched == [
        "https://storage.googleapis.com/open-buildings-data/v3/polygons_s2_level_4_gzip/"
        "107_buildings.csv.gz"
    ]


def test_flood_tiles_are_read_from_disk_once_downloaded(tmp_path, settings, monkeypatch):
    from apps.analysis.providers import SurfaceWaterAndFloods

    settings.FLOOD_DATA_DIR = str(tmp_path)
    floods = SurfaceWaterAndFloods()
    name = "ID118_N10_W0_RP100_depth.tif"
    monkeypatch.setattr(floods, "_flood_tile_names", lambda rp: [name])
    fetched = []
    monkeypatch.setattr(
        "apps.osm.loader.download", lambda url, path, client=None: fetched.append((url, path))
    )
    assert floods.download(log=lambda _m: None) == [name]
    assert fetched[0][0].endswith(f"/RP100/{name}") and fetched[0][1] == tmp_path / "RP100" / name

    (tmp_path / "RP100").mkdir()
    (tmp_path / "RP100" / name).write_bytes(b"")
    monkeypatch.undo()
    settings.FLOOD_DATA_DIR = str(tmp_path)
    assert SurfaceWaterAndFloods()._flood_tile_names(100) == [name]  # no listing request
