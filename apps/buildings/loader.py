"""Load Google Open Buildings v3 footprints for Cameroon into PostGIS.

The data comes as gzipped CSV files, one per S2 level-4 cell; six cells cover Cameroon (two of
them reach well into Nigeria). Each row holds the building's centre, area, confidence score and
outline (WKT). Only buildings whose centre lies inside the Cameroon outline are kept; the
confidence cut-off is applied at query time (a threshold), so it can change without a reload.
"""

import csv
import gzip
import logging
import time
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import connection, transaction
from django.utils import timezone

from apps.osm.loader import download as download_file

from .models import Building, BuildingRelease, ReleaseStatus

logger = logging.getLogger(__name__)

VERSION = "v3"
# S2 level-4 cells touching Cameroon, from the Open Buildings tiles.geojson index.
TILES = ("105", "107", "109", "10f", "111", "11b")


def tile_url(tile):
    return settings.OPEN_BUILDINGS_URL.format(tile=tile)


def tile_path(tile):
    return Path(settings.BUILDINGS_DATA_DIR) / f"{tile}_buildings.csv.gz"


def download(tiles=TILES, log=print):
    """Download the missing tile files; returns their paths."""
    paths = []
    for tile in tiles:
        path = tile_path(tile)
        if not path.exists():
            log(f"Downloading {tile_url(tile)} ...")
            download_file(tile_url(tile), path)
        paths.append(path)
    return paths


def read_rows(paths, outline, log=print):
    """Yield (ewkt, area_m2, confidence, plus_code) for each building centred in the outline."""
    csv.field_size_limit(10_000_000)
    prepared = outline.prepared
    west, south, east, north = outline.extent
    for path in paths:
        kept = seen = 0
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            col = {name: i for i, name in enumerate(header)}
            lat_i, lon_i, geom_i = col["latitude"], col["longitude"], col["geometry"]
            area_i, conf_i, code_i = col["area_in_meters"], col["confidence"], col["full_plus_code"]
            for row in reader:
                seen += 1
                lat, lon = float(row[lat_i]), float(row[lon_i])
                if not (west <= lon <= east and south <= lat <= north):
                    continue
                if not row[geom_i].startswith("POLYGON") or not prepared.contains(Point(lon, lat)):
                    continue
                kept += 1
                yield (
                    f"SRID=4326;{row[geom_i]}",
                    float(row[area_i]),
                    float(row[conf_i]),
                    row[code_i][:16],
                )
        log(f"{Path(path).name}: {kept:,} of {seen:,} buildings are in Cameroon")


def load(paths, source_url="", outline=None, log=print):
    """Load the files as a new release, then make it the active one."""
    from apps.gazetteer.boundaries import cameroon_outline

    outline = outline or cameroon_outline()
    release = BuildingRelease.objects.create(
        version=VERSION, source_url=source_url or ", ".join(str(p) for p in paths)
    )
    started = time.monotonic()
    try:
        _copy(release.pk, read_rows(paths, outline, log=log))
        _tidy(release.pk)
        _activate(release, Building.objects.filter(release=release).count())
    except Exception as exc:
        Building.objects.filter(release=release)._raw_delete(Building.objects.db)
        release.status, release.error = ReleaseStatus.FAILED, repr(exc)[:2000]
        release.save(update_fields=["status", "error"])
        raise
    logger.info("Building release %s: %s buildings in %.0f s", release.pk, release.count,
                time.monotonic() - started)  # fmt: skip
    return release


def _copy(release_id, rows):
    count = 0
    columns = "release_id, geom, area_m2, confidence, plus_code"
    with connection.cursor() as cursor:
        raw = cursor.cursor  # the psycopg cursor, for COPY
        with raw.copy(f"COPY {Building._meta.db_table} ({columns}) FROM STDIN") as copy:
            for ewkt, area, confidence, code in rows:
                copy.write_row((release_id, ewkt, area, confidence, code))
                count += 1
    return count


def _tidy(release_id):
    """Repair the few invalid outlines that stay single polygons; drop the rest."""
    table = Building._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET geom = ST_MakeValid(geom) WHERE release_id = %s "
            "AND NOT ST_IsValid(geom) AND GeometryType(ST_MakeValid(geom)) = 'POLYGON'",
            [release_id],
        )
        cursor.execute(
            f"DELETE FROM {table} WHERE release_id = %s AND NOT ST_IsValid(geom)", [release_id]
        )
        cursor.execute(f"ANALYZE {table}")


def _activate(release, count):
    with transaction.atomic():
        old = list(BuildingRelease.objects.filter(status=ReleaseStatus.ACTIVE).select_for_update())
        BuildingRelease.objects.filter(pk__in=[o.pk for o in old]).update(
            status=ReleaseStatus.RETIRED
        )
        release.status, release.count = ReleaseStatus.ACTIVE, count
        release.finished_at = timezone.now()
        release.save(update_fields=["status", "count", "finished_at"])
    Building.objects.filter(release__status=ReleaseStatus.RETIRED)._raw_delete(Building.objects.db)
