"""Load the features the analysis needs from a Geofabrik .osm.pbf extract into PostGIS.

What is kept (see `classify`): buildings, rivers/streams/canals, water bodies, wetlands, roads
(with a paved flag), schools, health facilities, markets and water points. Drains and ditches
are left out on purpose (they line most streets in Douala and Yaoundé).
"""

import logging
import struct
import time
from pathlib import Path

import httpx
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import Category, ImportStatus, OsmFeature, OsmImport

logger = logging.getLogger(__name__)

SERVICES = {Category.SCHOOL, Category.HEALTH, Category.MARKET, Category.WATER_POINT}

ROAD_KINDS = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
    "living_street", "service", "track", "road",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}  # fmt: skip
PAVED_SURFACES = {
    "paved", "asphalt", "concrete", "concrete:plates", "concrete:lanes", "paving_stones",
    "sett", "cobblestone", "chipseal", "metal",
}  # fmt: skip
UNPAVED_SURFACES = {
    "unpaved", "dirt", "earth", "ground", "gravel", "fine_gravel", "compacted", "sand", "mud",
    "grass", "laterite", "pebblestone", "rock",
}  # fmt: skip
# Without a surface tag, only the main road classes are assumed paved.
PAVED_BY_DEFAULT = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}
HEALTH_AMENITIES = {"hospital", "clinic", "doctors", "health_post"}
HEALTHCARE = {"hospital", "clinic", "centre", "doctor", "health_post"}
WATER_POINT_AMENITIES = {"drinking_water", "water_point"}
WATER_POINT_MAN_MADE = {"water_well", "water_tap", "borehole"}

FILTER_KEYS = ("building", "highway", "waterway", "natural", "landuse", "amenity", "healthcare",
               "man_made", "boundary", "leisure", "power", "railway")  # fmt: skip


def paved(tags):
    surface = tags.get("surface", "")
    if surface in PAVED_SURFACES:
        return True
    if surface in UNPAVED_SURFACES:
        return False
    return True if tags.get("highway") in PAVED_BY_DEFAULT else None


def classify(tags, shape):
    """[(category, kind, paved)] for an OSM object with these tags. `shape` is "point",
    "line" (an open or closed way) or "area" (a closed way or multipolygon relation)."""
    found = []
    if shape == "area":
        if tags.get("building", "no") != "no":
            found.append((Category.BUILDING, tags["building"][:40], None))
        if (
            tags.get("natural") == "water"
            or tags.get("waterway") == "riverbank"
            or (tags.get("landuse") == "reservoir")
        ):
            found.append((Category.WATER, tags.get("water", "water")[:40], None))
        if tags.get("natural") == "wetland":
            found.append((Category.WETLAND, tags.get("wetland", "wetland")[:40], None))
        if tags.get("boundary") in {"protected_area", "national_park"} or (
            tags.get("leisure") == "nature_reserve"
        ):
            kind = tags.get("protection_title") or tags.get("boundary") or tags["leisure"]
            found.append((Category.PROTECTED, kind[:40], None))
    if shape == "line":
        if tags.get("waterway") in {"river", "stream", "canal"}:
            found.append((Category.WATERWAY, tags["waterway"], None))
        if tags.get("highway") in ROAD_KINDS and tags.get("area") != "yes":
            found.append((Category.ROAD, tags["highway"], paved(tags)))
        if tags.get("power") == "line":  # high-voltage; "minor_line" is local distribution
            found.append((Category.POWER_LINE, tags.get("voltage", "line")[:40], None))
        if tags.get("railway") == "rail":
            found.append((Category.RAILWAY, "rail", None))
        if tags.get("natural") == "coastline":
            found.append((Category.COASTLINE, "coastline", None))
    if shape in {"point", "area"}:  # a service mapped as a building outline counts once
        amenity = tags.get("amenity", "")
        if amenity == "school":
            found.append((Category.SCHOOL, "school", None))
        if amenity in HEALTH_AMENITIES or tags.get("healthcare") in HEALTHCARE:
            found.append((Category.HEALTH, (amenity or tags["healthcare"])[:40], None))
        if amenity == "marketplace":
            found.append((Category.MARKET, "marketplace", None))
        if (
            amenity in WATER_POINT_AMENITIES
            or tags.get("man_made") in WATER_POINT_MAN_MADE
            or tags.get("natural") == "spring"
        ):
            found.append((Category.WATER_POINT, amenity or tags.get("man_made") or "spring", None))
    return found


def ewkb(wkb_hex):
    """Add SRID 4326 to a (multi)geometry's WKB header so COPY can store it directly."""
    data = bytes.fromhex(wkb_hex)
    fmt = "<I" if data[0] == 1 else ">I"
    (geom_type,) = struct.unpack(fmt, data[1:5])
    header = data[:1] + struct.pack(fmt, geom_type | 0x20000000) + struct.pack(fmt, 4326)
    return (header + data[5:]).hex()


def extract_path():
    return Path(settings.OSM_DATA_DIR) / "cameroon.osm.pbf"


def download(url=None, path=None, attempts=3, client=None):
    """Download the extract; a stalled transfer resumes where it stopped (HTTP Range)."""
    url, path = url or settings.OSM_EXTRACT_URL, path or extract_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.unlink(missing_ok=True)
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=120))
    for attempt in range(1, attempts + 1):
        done = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                if done and response.status_code != 206:  # server ignored the range
                    done = 0
                with partial.open("ab" if done else "wb") as out:
                    for chunk in response.iter_bytes():  # as received, so a stall loses nothing
                        out.write(chunk)
            partial.replace(path)
            return path
        except httpx.TransportError:
            if attempt == attempts:
                raise
            logger.warning("Extract download interrupted (attempt %s), resuming", attempt)
            time.sleep(10 * attempt)
    return path


def read_features(path):
    """Yield (category, kind, name, paved, osm_ref, ewkb_hex) for every kept feature."""
    import osmium

    factory = osmium.geom.WKBFactory()
    processor = (
        osmium.FileProcessor(str(path))
        .with_locations()
        .with_areas()
        .with_filter(osmium.filter.KeyFilter(*FILTER_KEYS))
    )
    for obj in processor:
        if obj.is_node():
            shape, ref, make = "point", f"n{obj.id}", factory.create_point
        elif obj.is_way():
            shape, ref, make = "line", f"w{obj.id}", factory.create_linestring
        elif obj.is_area():
            prefix = "w" if obj.from_way() else "r"
            shape, ref, make = "area", f"{prefix}{obj.orig_id()}", factory.create_multipolygon
        else:
            continue
        tags = {tag.k: tag.v for tag in obj.tags}
        found = classify(tags, shape)
        if not found:
            continue
        try:
            geometry = ewkb(make(obj))
        except (RuntimeError, osmium.InvalidLocationError):  # broken or incomplete geometry
            continue
        name = tags.get("name", "")[:200]
        for category, kind, is_paved in found:
            yield category, kind, name, is_paved, ref, geometry


def load(path, source_url=""):
    """Load an extract as a new import, then make it the active one."""
    import osmium

    header = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING).header()
    stamp = header.get("osmosis_replication_timestamp", "")
    osm_import = OsmImport.objects.create(source_url=source_url or str(path), data_timestamp=stamp)
    started = time.monotonic()
    try:
        counts = _copy(osm_import.pk, read_features(path))
        _tidy(osm_import.pk)
        _activate(osm_import, counts)
    except Exception as exc:
        OsmFeature.objects.filter(osm_import=osm_import)._raw_delete(OsmFeature.objects.db)
        osm_import.status, osm_import.error = ImportStatus.FAILED, repr(exc)[:2000]
        osm_import.save(update_fields=["status", "error"])
        raise
    logger.info("OSM import %s loaded in %.0f s: %s", osm_import.pk, time.monotonic() - started,
                counts)  # fmt: skip
    return osm_import


def _copy(import_id, rows):
    counts = {}
    columns = "osm_import_id, category, kind, name, paved, osm_ref, geom"
    with connection.cursor() as cursor:
        raw = cursor.cursor  # the psycopg cursor, for COPY
        with raw.copy(f"COPY {OsmFeature._meta.db_table} ({columns}) FROM STDIN") as copy:
            for category, kind, name, is_paved, ref, geometry in rows:
                copy.write_row((import_id, category, kind, name, is_paved, ref, geometry))
                counts[category] = counts.get(category, 0) + 1
    return counts


def _tidy(import_id):
    """Services become one point each; polygons are made valid for intersection tests."""
    table = OsmFeature._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET geom = ST_PointOnSurface(geom) "
            "WHERE osm_import_id = %s AND category = ANY(%s) AND GeometryType(geom) <> 'POINT'",
            [import_id, [str(c) for c in SERVICES]],
        )
        cursor.execute(
            f"UPDATE {table} SET geom = ST_CollectionExtract(ST_MakeValid(geom), 3) "
            "WHERE osm_import_id = %s AND GeometryType(geom) = 'MULTIPOLYGON' "
            "AND NOT ST_IsValid(geom)",
            [import_id],
        )
        cursor.execute(f"ANALYZE {table}")


def _activate(osm_import, counts):
    with transaction.atomic():
        old = list(OsmImport.objects.filter(status=ImportStatus.ACTIVE).select_for_update())
        OsmImport.objects.filter(pk__in=[o.pk for o in old]).update(status=ImportStatus.RETIRED)
        osm_import.status, osm_import.counts = ImportStatus.ACTIVE, counts
        osm_import.finished_at = timezone.now()
        osm_import.save(update_fields=["status", "counts", "finished_at"])
    # Drop the retired features (fast raw delete: nothing points at features).
    OsmFeature.objects.filter(osm_import__status=ImportStatus.RETIRED)._raw_delete(
        OsmFeature.objects.db
    )
