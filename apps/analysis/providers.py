"""External data behind small interfaces, so sources can be swapped without touching modules
(TRD §9.4). Tests replace `elevation_provider` / `buildings_provider` with fakes."""

import json
import math
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol

import httpx
import numpy as np
from django.conf import settings
from django.contrib.gis.geos import LineString, MultiPolygon, Polygon


@dataclass
class Elevation:
    """A DEM window: heights in metres (NaN = no data) and its affine transform (lon/lat)."""

    heights: np.ndarray
    transform: object  # affine.Affine
    dataset: str
    version: str


class ElevationProvider(Protocol):
    def read(self, west: float, south: float, east: float, north: float) -> Elevation: ...


class CopernicusDEM:
    """Copernicus DEM GLO-30 cloud-optimised GeoTIFFs on the AWS open-data bucket.

    Only the window around the parcel is fetched (HTTP range requests), not whole tiles.
    """

    BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
    dataset = "copernicus-dem-glo30"
    version = "GLO-30 (2021)"

    @classmethod
    def tile_path(cls, lat, lon):
        ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
        name = f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"
        return f"/vsicurl/{cls.BASE}/{name}/{name}.tif"

    def read(self, west, south, east, north):
        import rasterio
        from rasterio.merge import merge

        paths = [
            self.tile_path(lat, lon)
            for lat in range(math.floor(south), math.floor(north) + 1)
            for lon in range(math.floor(west), math.floor(east) + 1)
        ]
        from rasterio.session import DummySession

        with rasterio.Env(
            DummySession(),
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        ):
            sources = [rasterio.open(p) for p in paths]
            try:
                mosaic, transform = merge(
                    sources, bounds=(west, south, east, north), nodata=np.nan, dtype="float32"
                )
            finally:
                for src in sources:
                    src.close()
        return Elevation(mosaic[0], transform, self.dataset, self.version)


@dataclass
class Buildings:
    footprints: list  # GEOS polygons, SRID 4326
    dataset: str
    version: str
    confidences: list | None = None  # per footprint, when the source scores its detections


class BuildingsProvider(Protocol):
    def fetch(self, west: float, south: float, east: float, north: float) -> Buildings: ...


class Overpass:
    """OpenStreetMap data from the Overpass API (ODbL). Public servers are often busy, so each
    query is retried with backoff and then sent to the next server in OVERPASS_URL."""

    RETRY_STATUS = {429, 502, 503, 504}
    ATTEMPTS_PER_SERVER = 2

    def __init__(self, urls=None, client=None, backoff_s=3):
        self.urls = urls or [u.strip() for u in settings.OVERPASS_URL.split(",") if u.strip()]
        self.client = client or httpx.Client(timeout=60)
        self.backoff_s = backoff_s

    def query(self, ql):
        last_error = None
        for url in self.urls:
            for attempt in range(self.ATTEMPTS_PER_SERVER):
                try:
                    response = self.client.post(
                        url,
                        data={"data": ql},
                        headers={"User-Agent": settings.NOMINATIM_USER_AGENT},
                    )
                    if response.status_code not in self.RETRY_STATUS:
                        response.raise_for_status()
                        return response.json()
                    last_error = httpx.HTTPStatusError(
                        f"{response.status_code} from {url}",
                        request=response.request,
                        response=response,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                time.sleep(self.backoff_s * (attempt + 1))
        raise last_error


@dataclass
class WaterFeatures:
    lines: list  # rivers, streams, canals (GEOS LineStrings, 4326)
    areas: list  # lakes, ponds, riverbanks (GEOS polygons)
    wetlands: list  # GEOS polygons
    dataset: str
    version: str


class OverpassWater(Overpass):
    """Natural water only. Drains and ditches are left out: in Douala and Yaoundé they line
    most streets, so counting them would put every plot "next to water"."""

    dataset = "osm-water"

    def fetch(self, west, south, east, north):
        box = f"({south},{west},{north},{east})"
        payload = self.query(
            "[out:json][timeout:50];("
            f'way["waterway"~"^(river|stream|canal)$"]{box};'
            f'way["natural"~"^(water|wetland)$"]{box};'
            f'relation["natural"~"^(water|wetland)$"]{box};'
            ");out geom;"
        )
        lines, areas, wetlands = [], [], []
        for element in payload["elements"]:
            tags = element.get("tags", {})
            if "waterway" in tags and element.get("type") == "way":
                points = [(pt["lon"], pt["lat"]) for pt in element.get("geometry", [])]
                if len(points) >= 2:
                    lines.append(LineString(points, srid=4326))
                continue
            polygon = _osm_polygon(element)
            if polygon is not None:
                (wetlands if tags.get("natural") == "wetland" else areas).append(polygon)
        stamp = payload.get("osm3s", {}).get("timestamp_osm_base", "")
        return WaterFeatures(lines, areas, wetlands, self.dataset, stamp)


def _closed_ring(points):
    ring = [(pt["lon"], pt["lat"]) for pt in points]
    return ring if ring[0] == ring[-1] else [*ring, ring[0]]


def _valid(polygon):
    """Repair an invalid polygon; the result may be a MultiPolygon."""
    return polygon if polygon.valid else polygon.buffer(0)


def _parts(geom):
    """Plain polygons from a Polygon or MultiPolygon (empty geometries dropped)."""
    if geom.empty:
        return []
    return list(geom) if geom.geom_type == "MultiPolygon" else [geom]


def _assemble_rings(ways):
    """Join a relation's member ways end to end into closed rings. Large water bodies are
    mapped as many open ways; unclosable leftovers are dropped."""
    pending = [[(pt["lon"], pt["lat"]) for pt in way] for way in ways if len(way) >= 2]
    rings = []
    while pending:
        ring = pending.pop()
        while ring[0] != ring[-1]:
            for i, way in enumerate(pending):
                if way[0] == ring[-1]:
                    ring += way[1:]
                elif way[-1] == ring[-1]:
                    ring += way[-2::-1]
                else:
                    continue
                pending.pop(i)
                break
            else:
                break  # cannot be closed
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _osm_polygon(element):
    """A GEOS polygon or multipolygon from an Overpass way or multipolygon relation, or None."""
    if element.get("type") == "way" and len(element.get("geometry", [])) >= 3:
        return _valid(Polygon(_closed_ring(element["geometry"]), srid=4326))
    if element.get("type") == "relation":
        members = element.get("members", [])

        def rings(role):
            ways = [m["geometry"] for m in members if m.get("role") == role and m.get("geometry")]
            return [Polygon(r, srid=4326) for r in _assemble_rings(ways)]

        outers = [part for outer in rings("outer") for part in _parts(_valid(outer))]
        if not outers:
            return None
        shape = MultiPolygon(*outers, srid=4326).unary_union
        for inner in rings("inner"):
            shape = shape.difference(_valid(inner))
        parts = _parts(shape)
        return MultiPolygon(*parts, srid=4326) if parts else None
    return None


@dataclass
class Composite:
    """Cloud-masked median of several Sentinel-2 scenes on a 10 m UTM grid.

    Bands are surface reflectance (0–1); NaN where no scene saw the ground clearly.
    """

    bands: dict
    transform: object  # affine.Affine, in `crs_epsg`
    crs_epsg: int
    scene_dates: list
    dataset: str = "sentinel-2-l2a"


class ImageryProvider(Protocol):
    def composite(self, west, south, east, north, start, end) -> Composite | None: ...


class EarthSearchSentinel2:
    """Sentinel-2 L2A cloud-optimised GeoTIFFs from the AWS open-data catalogue.

    Only the window around the parcel is read from each band. Clouds, shadows and cirrus are
    masked with the scene classification (SCL) before taking the per-pixel median.
    """

    URL = "https://earth-search.aws.element84.com/v1"
    BANDS = ("blue", "green", "red", "nir", "swir16")
    CLEAR_SCL = (4, 5, 6, 7, 11)  # vegetation, bare soil, water, unclassified, snow
    RESOLUTION = 10

    def __init__(self, max_scene_cloud=70, max_scenes=6):
        self.max_scene_cloud = max_scene_cloud
        self.max_scenes = int(max_scenes)

    def composite(self, west, south, east, north, start, end):
        from pystac_client import Client

        items = list(
            Client.open(self.URL)
            .search(
                collections=["sentinel-2-l2a"],
                bbox=[west, south, east, north],
                datetime=f"{start.isoformat()}/{end.isoformat()}",
                query={"eo:cloud_cover": {"lt": self.max_scene_cloud}},
                sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
                max_items=self.max_scenes,
            )
            .items()
        )
        if not items:
            return None
        epsg = 32632 if (west + east) / 2 < 12 else 32633
        transform, width, height = _utm_grid(west, south, east, north, epsg, self.RESOLUTION)

        with ThreadPoolExecutor(max_workers=6) as pool:
            scenes = list(
                pool.map(lambda item: self._scene(item, epsg, transform, width, height), items)
            )
        stacked = {band: np.stack([scene[band] for scene in scenes]) for band in self.BANDS}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN pixels stay NaN
            bands = {
                band: np.nanmedian(stack, axis=0).astype("float32")
                for band, stack in stacked.items()
            }
        dates = sorted(item.datetime.date().isoformat() for item in items)
        return Composite(bands, transform, epsg, dates)

    def _scene(self, item, epsg, transform, width, height):
        scl = _read_window(item.assets["scl"].href, epsg, transform, width, height)
        clear = np.isin(scl, self.CLEAR_SCL)
        scene = {}
        for band in self.BANDS:
            scale, offset = reflectance_params(item, band)
            raw = _read_window(item.assets[band].href, epsg, transform, width, height).astype(
                "float32"
            )
            values = raw * scale + offset
            values[(~clear) | (raw == 0)] = np.nan
            scene[band] = values
        return scene


def reflectance_params(item, band):
    """(scale, offset) turning stored values into surface reflectance.

    Since processing baseline 04.00 (Jan 2022) ESA adds +1000 to L2A values, and Earth Search
    lists offset −0.1 for those scenes. But when a scene says `earthsearch:boa_offset_applied`,
    its stored values were already corrected: applying the offset again makes every recent
    reflectance 0.1 too low (checked on forest and city scenes from 2020 and 2026).
    """
    info = (item.assets[band].extra_fields.get("raster:bands") or [{}])[0]
    scale = info.get("scale", 0.0001)
    if item.properties.get("earthsearch:boa_offset_applied"):
        return scale, 0.0
    return scale, info.get("offset", 0.0)


def _utm_grid(west, south, east, north, epsg, resolution):
    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds

    x0, y0, x1, y1 = transform_bounds("EPSG:4326", f"EPSG:{epsg}", west, south, east, north)
    x0, y1 = math.floor(x0 / resolution) * resolution, math.ceil(y1 / resolution) * resolution
    width = math.ceil((x1 - x0) / resolution)
    height = math.ceil((y1 - y0) / resolution)
    return from_origin(x0, y1, resolution, resolution), width, height


def _read_window(href, epsg, transform, width, height):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.session import DummySession
    from rasterio.vrt import WarpedVRT

    # Public bucket over HTTPS: no AWS session (the app's own storage keys must not be used).
    with rasterio.Env(
        DummySession(), GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES"
    ):
        with rasterio.open(f"/vsicurl/{href}") as src:
            with WarpedVRT(
                src,
                crs=f"EPSG:{epsg}",
                transform=transform,
                width=width,
                height=height,
                resampling=Resampling.nearest,
            ) as vrt:
                return vrt.read(1)


@dataclass
class Grid:
    """A raster window in lon/lat with its affine transform (rows top to bottom)."""

    values: np.ndarray
    transform: object


def _read_mosaic(paths, west, south, east, north, nodata):
    """Read the window from one or several (tile) GeoTIFFs, local or over HTTP, as float32."""
    import rasterio
    from rasterio.merge import merge
    from rasterio.session import DummySession

    with rasterio.Env(
        DummySession(),
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    ):
        sources = [
            rasterio.open(path if path.startswith("/") else f"/vsicurl/{path}") for path in paths
        ]
        try:
            mosaic, transform = merge(
                sources, bounds=(west, south, east, north), nodata=nodata, dtype="float32"
            )
        finally:
            for source in sources:
                source.close()
    return Grid(mosaic[0], transform)


def _tiles(west, south, east, north, size=10):
    """(left lon, top lat) of each 10° tile touching the box; tiles are named by that corner."""
    lefts = range(math.floor(west / size) * size, math.floor(east / size) * size + 1, size)
    tops = range(math.ceil(south / size) * size, math.ceil(north / size) * size + 1, size)
    return [(left, top) for left in lefts for top in tops]


class SurfaceWaterAndFloods:
    """JRC Global Surface Water occurrence (1984–2021, ~30 m), read as small windows over HTTP,
    and the Copernicus EMS / JRC river flood hazard depth (~90 m), read from the local tiles
    (manage.py load_flood) or over HTTP until they are downloaded."""

    GSW = "https://storage.googleapis.com/global-surface-water/downloads2021/occurrence/"
    FLOOD = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/CEMS-GLOFAS/flood_hazard/"
    gsw_dataset, gsw_version = "jrc-gsw", "v1.4 (1984–2021)"
    flood_dataset, flood_version = "jrc-flood-hazard", "v2.1.2"

    def occurrence(self, west, south, east, north):
        """Per cent of observations with water (0–100); NaN where unknown (255)."""
        paths = [
            f"{self.GSW}occurrence_{abs(left)}{'E' if left >= 0 else 'W'}_"
            f"{abs(top)}{'N' if top >= 0 else 'S'}v1_4_2021.tif"
            for left, top in _tiles(west, south, east, north)
        ]
        grid = _read_mosaic(paths, west, south, east, north, nodata=255)
        grid.values[grid.values == 255] = np.nan
        return grid

    CAMEROON = (8.4, 1.6, 16.2, 13.1)

    def flood_depth(self, west, south, east, north, return_period=100):
        """Flood depth in metres for the return period; 0 where not flooded. None if no tile
        covers the area (no modelled river flooding there)."""
        paths = []
        for name in self._names_for(west, south, east, north, return_period):
            local = self.local_tile(return_period, name)
            paths.append(str(local) if local.exists() else f"{self.FLOOD}RP{return_period}/{name}")
        if not paths:
            return None
        grid = _read_mosaic(paths, west, south, east, north, nodata=-9999)
        grid.values[~np.isfinite(grid.values) | (grid.values < 0)] = 0
        return grid

    @staticmethod
    def local_tile(return_period, name):
        from pathlib import Path

        return Path(settings.FLOOD_DATA_DIR) / f"RP{return_period}" / name

    def _names_for(self, west, south, east, north, return_period):
        names = self._flood_tile_names(return_period)
        found = []
        for left, top in _tiles(west, south, east, north):
            key = f"_{'N' if top >= 0 else 'S'}{abs(top)}_{'E' if left > 0 else 'W'}{abs(left)}_"
            found += [n for n in names if key in n][:1]
        return found

    def _flood_tile_names(self, return_period):
        """Tile names: those downloaded, else the JRC listing (cached for a month)."""
        import re

        from django.core.cache import cache

        folder = self.local_tile(return_period, "x").parent
        local = sorted(p.name for p in folder.glob("*.tif")) if folder.is_dir() else []
        if local:
            return local
        key = f"jrc-flood-tiles:{return_period}"
        names = cache.get(key)
        if names is None:
            listing = httpx.get(f"{self.FLOOD}RP{return_period}/", timeout=30)
            pattern = rf"ID\d+_[NS]\d+_[EW]\d+_RP{return_period}_depth\.tif"
            names = sorted(set(re.findall(pattern, listing.raise_for_status().text)))
            cache.set(key, names, 60 * 60 * 24 * 30)
        return names

    def download(self, return_period=100, client=None, log=print):
        """Download the depth tiles covering Cameroon (manage.py load_flood)."""
        from apps.osm.loader import download as download_file

        names = self._names_for(*self.CAMEROON, return_period)
        for name in names:
            target = self.local_tile(return_period, name)
            if not target.exists():
                download_file(f"{self.FLOOD}RP{return_period}/{name}", target, client=client)
            log(f"RP{return_period} {name}: ready")
        return names


class GhslTiles:
    """A GHSL R2023A product (~90 m, epochs 1975–2030 every 5 years; 2025 and 2030 are
    projections), read from local copies (manage.py load_ghsl) or over HTTP from the zipped
    10° tiles."""

    BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    PRODUCT = ""
    version = "R2023A"
    TOP, LEFT = 89.0995832, -180.0079166  # the tile grid's origin
    EPOCHS = ()
    CAMEROON = (8.4, 1.6, 16.2, 13.1)

    def tiles(self, west, south, east, north):
        rows = range(int((self.TOP - north) // 10) + 1, int((self.TOP - south) // 10) + 2)
        cols = range(int((west - self.LEFT) // 10) + 1, int((east - self.LEFT) // 10) + 2)
        return [(r, c) for r in rows for c in cols]

    def name(self, epoch):
        return f"{self.PRODUCT}_E{epoch}_GLOBE_R2023A_4326_3ss"

    def tile_url(self, epoch, row, col):
        name = self.name(epoch)
        folder = f"{self.BASE}{self.PRODUCT}_GLOBE_R2023A/{name}/V1-0/tiles"
        return f"{folder}/{name}_V1_0_R{row}_C{col}.zip"

    def local_zip(self, epoch, row, col):
        from pathlib import Path

        return Path(settings.GHSL_DATA_DIR) / f"{self.name(epoch)}_V1_0_R{row}_C{col}.zip"

    def _paths(self, west, south, east, north, epoch):
        """Local copies (manage.py load_ghsl) when present, else the zips over HTTP."""
        paths = []
        for row, col in self.tiles(west, south, east, north):
            inner = f"{self.name(epoch)}_V1_0_R{row}_C{col}.tif"
            local = self.local_zip(epoch, row, col)
            source = str(local) if local.exists() else f"/vsicurl/{self.tile_url(epoch, row, col)}"
            paths.append(f"/vsizip/{source}/{inner}")
        return paths

    def download(self, client=None, log=print):
        client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=180))
        for epoch in self.EPOCHS:
            for row, col in self.tiles(*self.CAMEROON):
                target = self.local_zip(epoch, row, col)
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix(".part")
                with client.stream("GET", self.tile_url(epoch, row, col)) as response:
                    response.raise_for_status()
                    with partial.open("wb") as out:
                        for chunk in response.iter_bytes():
                            out.write(chunk)
                partial.replace(target)
                log(f"{self.PRODUCT} {epoch} R{row} C{col}: ready")

    def _mosaic(self, west, south, east, north, epoch):
        import rasterio
        from rasterio.merge import merge
        from rasterio.session import DummySession

        with rasterio.Env(DummySession(), GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            sources = [rasterio.open(p) for p in self._paths(west, south, east, north, epoch)]
            try:
                mosaic, transform = merge(
                    sources, bounds=(west, south, east, north), nodata=0, dtype="float32"
                )
            finally:
                for source in sources:
                    source.close()
        return Grid(mosaic[0], transform)


class GhslBuiltSurface(GhslTiles):
    """GHSL built-up surface: m² of buildings per cell."""

    dataset, PRODUCT = "ghsl-built-s", "GHS_BUILT_S"
    EPOCHS = (1975, 1990, 2000, 2010, 2020)  # the ones the urban-expansion map uses

    def built(self, west, south, east, north, epoch):
        return self._mosaic(west, south, east, north, epoch)


class GhslPopulation(GhslTiles):
    """GHSL population (GHS-POP): people per cell, a second model to compare trends with."""

    dataset, PRODUCT = "ghsl-pop", "GHS_POP"
    EPOCHS = (2000, 2005, 2010, 2015, 2020, 2025, 2030)
    PROJECTED_FROM = 2025

    def total(self, geom, epoch):
        """People in the cells whose centre falls inside the geometry."""
        import json

        from rasterio.features import geometry_mask

        grid = self._mosaic(*geom.extent, epoch)
        inside = geometry_mask(
            [json.loads(geom.json)],
            out_shape=grid.values.shape,
            transform=grid.transform,
            invert=True,
        )
        values = np.where(grid.values > 0, grid.values, 0)
        return float(values[inside].sum())


def ghsl_provider():
    return GhslBuiltSurface()


def ghsl_population_provider():
    return GhslPopulation()


class LocalOsm:
    """Features from the active OSM import (apps.osm), refreshed weekly from Geofabrik."""

    def __init__(self, osm_import):
        self.osm_import = osm_import
        self.version = osm_import.data_timestamp

    def _in_box(self, category, bounds):
        from apps.osm.queries import in_box

        return [f.geom for f in in_box(self.osm_import, category, *bounds)]


class GoogleOpenBuildings:
    """Footprints from the local Google Open Buildings copy (apps.buildings), detected from
    satellite imagery, so it covers informal areas OSM misses. Detections scoring below
    `min_confidence` are left out."""

    dataset = "google-open-buildings"

    def __init__(self, release, min_confidence):
        self.release, self.min_confidence = release, min_confidence
        self.version = release.version

    def fetch(self, west, south, east, north):
        from apps.buildings.queries import in_box

        rows = list(in_box(self.release, west, south, east, north, self.min_confidence))
        return Buildings(
            [b.geom for b in rows], self.dataset, self.version, [b.confidence for b in rows]
        )


class LocalOsmWater(LocalOsm):
    dataset = "osm-water"

    def fetch(self, west, south, east, north):
        from apps.osm.models import Category

        bounds = (west, south, east, north)
        return WaterFeatures(
            self._in_box(Category.WATERWAY, bounds),
            self._in_box(Category.WATER, bounds),
            self._in_box(Category.WETLAND, bounds),
            self.dataset,
            self.version,
        )


@dataclass
class Leg:
    seconds: float | None  # None: no route
    metres: float | None


class Valhalla:
    """Self-hosted Valhalla on the Cameroon extract: travel times and isochrones."""

    dataset = "valhalla-osm"
    COSTING = {"walk": "pedestrian", "drive": "auto"}

    def __init__(self, url=None, client=None):
        self.url = (url or settings.VALHALLA_URL).rstrip("/")
        self.client = client or httpx.Client(timeout=60)

    def _post(self, path, payload):
        response = self.client.post(f"{self.url}/{path}", json=payload)
        if response.status_code == 400:  # e.g. no road near a location: no route, not a failure
            return None
        response.raise_for_status()
        return response.json()

    def times(self, origin, targets, mode):
        """One Leg per target from origin (lon, lat), for mode "walk" or "drive"."""
        if not targets:
            return []
        payload = {
            "sources": [{"lon": origin[0], "lat": origin[1]}],
            "targets": [{"lon": lon, "lat": lat} for lon, lat in targets],
            "costing": self.COSTING[mode],
        }
        data = self._post("sources_to_targets", payload)
        if data is None:
            return [Leg(None, None) for _ in targets]
        legs = data["sources_to_targets"][0]
        return [
            Leg(leg.get("time"), None if leg.get("distance") is None else leg["distance"] * 1000)
            for leg in legs
        ]

    def isochrones(self, origin, mode, minutes):
        """{minutes: GEOS (Multi)Polygon} of the area reachable within each time."""
        from django.contrib.gis.geos import GEOSGeometry

        payload = {
            "locations": [{"lon": origin[0], "lat": origin[1]}],
            "costing": self.COSTING[mode],
            "contours": [{"time": m} for m in minutes],
            "polygons": True,
        }
        data = self._post("isochrone", payload)
        areas = {}
        for feature in (data or {}).get("features", []):
            geom = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
            areas[int(round(feature["properties"]["contour"]))] = geom
        return areas


def _active_osm():
    from apps.osm.models import OsmImport

    return OsmImport.active()


def water_provider():
    return SurfaceWaterAndFloods()


def water_features_provider():
    osm_import = _active_osm()
    return LocalOsmWater(osm_import) if osm_import else OverpassWater()


def imagery_provider() -> ImageryProvider:
    from .config import thresholds

    t = thresholds()
    return EarthSearchSentinel2(t.imagery_max_scene_cloud, t.imagery_max_scenes)


def elevation_provider() -> ElevationProvider:
    return CopernicusDEM()


def buildings_provider() -> BuildingsProvider:
    """The local Google Open Buildings copy (manage.py load_buildings)."""
    from apps.buildings.models import BuildingRelease

    from .config import thresholds

    release = BuildingRelease.active()
    if release is None:
        raise RuntimeError("No building footprints are loaded (manage.py load_buildings)")
    return GoogleOpenBuildings(release, thresholds().building_min_confidence)


def osm_provider():
    """The active OSM import (roads and services for the access module), or None."""
    return _active_osm()


def routing_provider():
    return Valhalla()
