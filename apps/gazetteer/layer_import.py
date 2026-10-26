"""Import admin-maintained constraint layers (FR-50) from GeoJSON, KML or a zipped shapefile:
one ReferenceLayer row per feature, attributes kept as properties."""

import tempfile
from pathlib import Path

from django.contrib.gis.gdal import DataSource, GDALException
from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.utils.translation import gettext as _

from apps.parcels.parsers import GeometryInputError, _materialise

from .models import ReferenceLayer

SUFFIXES = {".geojson", ".json", ".kml", ".zip"}
MAX_BYTES = 50 * 1024 * 1024


def _value(value):
    return value if isinstance(value, str | int | float | bool) or value is None else str(value)


def import_layer(uploaded, kind, name_field="", source="", valid_from=None, replace=False):
    """Create one ReferenceLayer per feature; returns the number created. With `replace`,
    the earlier features of the same kind and source are removed first (in one transaction)."""
    suffix = Path(uploaded.name or "").suffix.lower()
    if suffix not in SUFFIXES:
        raise GeometryInputError(_("Use GeoJSON, KML or a zipped shapefile."))
    if uploaded.size > MAX_BYTES:
        raise GeometryInputError(_("The file is too large (50 MB maximum)."))
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        path = _materialise(Path(tmp), suffix, uploaded.read())
        try:
            data = DataSource(str(path))
        except GDALException as exc:
            raise GeometryInputError(_("The file could not be read.")) from exc
        for layer in data:
            for number, feature in enumerate(layer, start=1):
                geom = feature.geom
                if geom.srs is not None and geom.srs.srid != 4326:
                    geom.transform(4326)
                geom.set_3d(False)
                properties = {f: _value(feature.get(f)) for f in layer.fields}
                name = str(properties.get(name_field) or "") if name_field else ""
                rows.append(
                    ReferenceLayer(
                        kind=kind,
                        name=(name or f"{source or kind} #{number}")[:200],
                        geometry=GEOSGeometry(geom.wkb, srid=4326),
                        properties=properties,
                        source=source[:200],
                        valid_from=valid_from,
                    )
                )
    if not rows:
        raise GeometryInputError(_("The file contains no features."))
    with transaction.atomic():
        if replace:
            ReferenceLayer.objects.filter(kind=kind, source=source).delete()
        ReferenceLayer.objects.bulk_create(rows)
    return len(rows)
