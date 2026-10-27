"""Official land-use layers from the Forest Atlas of Cameroon (MINFOF with WRI,
cmr-data.forest-atlas.org): protected areas, the permanent forest estate and concessions.

Each layer is read from its public ArcGIS feature service, or from a local export of the same
layer (shapefile, GeoJSON...), and stored as ReferenceLayer rows that the red-flags module
checks. Features that are only proposed, or whose classification is not finished, are marked
`proposed`, and Ramsar wetlands `advisory`: both rate amber rather than red.
"""

import json
from dataclasses import dataclass, field

import httpx
from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import GeometryCollection, GEOSGeometry
from django.db import transaction

from .management.commands.load_boundaries import fix_mojibake
from .models import ReferenceLayer, ReferenceLayerKind

SERVICES = "https://services3.arcgis.com/dwv7XaFMgpPo7FSx/arcgis/rest/services"
PAGE = 200
SOURCE_PREFIX = "MINFOF – Atlas forestier du Cameroun"


@dataclass(frozen=True)
class AtlasLayer:
    key: str
    service: str  # path under SERVICES, up to the layer number
    kind: str
    name_field: str
    title: str  # appended to the source, e.g. "Aires protégées de la faune"
    proposed: dict = field(default_factory=dict)  # {attribute: values meaning "not final"}
    advisory: bool = False  # a designation that restricts use without forbidding it: amber

    @property
    def source(self):
        return f"{SOURCE_PREFIX} ({self.title})"

    @property
    def url(self):
        return f"{SERVICES}/{self.service}"


LAYERS = {
    layer.key: layer
    for layer in [
        AtlasLayer(
            "protected_areas",
            "Aires_proteg%C3%A9es_de_la_faune/FeatureServer/0",
            ReferenceLayerKind.PROTECTED_AREA,
            "nom_ap",
            "Aires protégées de la faune",
            {"statu_crea": {"propose"}},
        ),
        AtlasLayer(
            "forest_reserves",
            "R%C3%A9serves_forestier/FeatureServer/0",
            ReferenceLayerKind.FOREST_ESTATE,
            "nom_res",
            "Réserves forestières",
            {"statu_crea": {"en_cours", None, ""}},
        ),
        AtlasLayer(
            "production_forests",
            "UFA/FeatureServer/0",
            ReferenceLayerKind.FOREST_ESTATE,
            "nom_foret",
            "Forêts de production et forêts communales",
            {"statu_class": {"en_cours", "non_classe", None, ""}},
        ),
        AtlasLayer(
            "plantations",
            "Plantation_agro/FeatureServer/0",
            ReferenceLayerKind.CONCESSION,
            "nom_plant",
            "Plantations agro-industrielles",
        ),
        AtlasLayer(
            "community_forests",
            "forets_communautaires/FeatureServer/0",
            ReferenceLayerKind.CONCESSION,
            "nom_fcom",
            "Forêts communautaires",
        ),
        AtlasLayer(
            "hunting_zones",
            "Zics/FeatureServer/0",
            ReferenceLayerKind.CONCESSION,
            "nom_zic",
            "Zones d'intérêt cynégétique",
        ),
        AtlasLayer(
            "ramsar_sites",
            "Conventions_internationales/FeatureServer/0",
            ReferenceLayerKind.PROTECTED_AREA,
            "nom_conv",
            "Conventions internationales",
            advisory=True,
        ),
    ]
}


def _clean(value):
    if isinstance(value, str):
        value = fix_mojibake(value.strip())
    return value if isinstance(value, str | int | float | bool) or value is None else str(value)


def _polygonal(geom):
    """The source has self-intersecting rings: repair them, keeping only the polygon parts."""
    geom = geom.make_valid()
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom if g.geom_type in {"Polygon", "MultiPolygon"}]
        geom = GeometryCollection(*parts, srid=4326).unary_union if parts else geom
    return geom


def fetch_features(layer, http=None):
    """(properties, GEOS geometry) pairs from the layer's feature service, page by page."""
    client = http or httpx.Client(timeout=120, follow_redirects=True)
    offset = 0
    try:
        while True:
            response = client.get(
                f"{layer.url}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "outSR": 4326,
                    "f": "geojson",
                    "resultOffset": offset,
                    "resultRecordCount": PAGE,
                },
            )
            response.raise_for_status()
            page = response.json()
            if "error" in page:
                raise ValueError(f"{layer.key}: {page['error']}")
            features = page.get("features") or []
            for feature in features:
                if feature.get("geometry"):
                    geom = GEOSGeometry(json.dumps(feature["geometry"]), srid=4326)
                    yield feature.get("properties") or {}, geom
            more = page.get("exceededTransferLimit") or page.get("properties", {}).get(
                "exceededTransferLimit"
            )
            if not features or (len(features) < PAGE and not more):
                return
            offset += len(features)
    finally:
        if http is None:
            client.close()


def read_file(path):
    """(properties, GEOS geometry) pairs from a local export of a layer, reprojected to WGS84."""
    data = DataSource(str(path), encoding="utf-8")
    for layer in data:
        for feature in layer:
            geom = feature.geom
            if geom.srs is not None and geom.srs.srid != 4326:
                geom.transform(4326)
            geom.set_3d(False)
            properties = {f: feature.get(f) for f in layer.fields}
            yield properties, GEOSGeometry(geom.wkb, srid=4326)


def is_proposed(layer, properties):
    lowered = {k.lower(): v for k, v in properties.items()}
    for attribute, values in layer.proposed.items():
        value = lowered.get(attribute)
        value = value.strip().lower() if isinstance(value, str) else value
        if value in values:
            return True
    return False


def load(layer, features):
    """Replace the layer's earlier features with `features`; returns the number stored."""
    rows = []
    for number, (properties, geom) in enumerate(features, start=1):
        properties = {k: _clean(v) for k, v in properties.items()}
        lowered = {k.lower(): v for k, v in properties.items()}
        name = str(lowered.get(layer.name_field) or "").strip()
        kind_label = str(lowered.get("desc_type") or "").strip()
        if kind_label and "�" not in kind_label:
            name = f"{name} ({kind_label})" if name else kind_label
        properties["proposed"] = is_proposed(layer, properties)
        properties["advisory"] = layer.advisory
        geom = _polygonal(geom)
        rows.append(
            ReferenceLayer(
                kind=layer.kind,
                name=(name or f"{layer.title} #{number}")[:200],
                geometry=geom,
                properties=properties,
                source=layer.source[:200],
            )
        )
    if not rows:
        raise ValueError(f"{layer.key}: no features")
    with transaction.atomic():
        ReferenceLayer.objects.filter(source=layer.source).delete()
        ReferenceLayer.objects.bulk_create(rows)
    return len(rows)
