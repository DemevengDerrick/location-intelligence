import json

import httpx
import pytest
from django.core.management import call_command

from apps.gazetteer import forest_atlas
from apps.gazetteer.models import ReferenceLayer, ReferenceLayerKind

pytestmark = pytest.mark.django_db


def feature(name, status="cree", x=9.7):
    return {
        "type": "Feature",
        "properties": {"nom_ap": name, "desc_type": "Parc national", "statu_crea": status},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[x, 4.0], [x + 0.1, 4.0], [x + 0.1, 4.1], [x, 4.1], [x, 4.0]]],
        },
    }


def service(pages):
    """A feature service answering `pages` (lists of features) by resultOffset."""

    def handler(request):
        offset = int(request.url.params["resultOffset"])
        index = sum(1 for _ in range(0, offset, forest_atlas.PAGE))
        features = pages[index] if index < len(pages) else []
        more = index < len(pages) - 1
        body = {"type": "FeatureCollection", "features": features}
        if more:
            body["properties"] = {"exceededTransferLimit": True}
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_layers_are_read_page_by_page_and_proposed_areas_marked(monkeypatch):
    monkeypatch.setattr(forest_atlas, "PAGE", 2)
    layer = forest_atlas.LAYERS["protected_areas"]
    pages = [[feature("Waza"), feature("Mefou", "propose")], [feature("Korup")]]
    count = forest_atlas.load(layer, forest_atlas.fetch_features(layer, http=service(pages)))
    assert count == 3
    areas = {r.name: r for r in ReferenceLayer.objects.all()}
    assert set(areas) == {"Waza (Parc national)", "Mefou (Parc national)", "Korup (Parc national)"}
    assert areas["Mefou (Parc national)"].properties["proposed"] is True
    assert areas["Waza (Parc national)"].properties["proposed"] is False
    assert areas["Waza (Parc national)"].kind == ReferenceLayerKind.PROTECTED_AREA
    assert areas["Waza (Parc national)"].source.startswith(forest_atlas.SOURCE_PREFIX)


def test_reloading_a_layer_replaces_only_its_own_features():
    layer = forest_atlas.LAYERS["protected_areas"]
    other = ReferenceLayer.objects.create(
        kind=ReferenceLayerKind.PROTECTED_AREA, name="Uploaded", geometry="POINT(9 4)", source="X"
    )
    gdal = [({"nom_ap": "A"}, forest_atlas.GEOSGeometry(json.dumps(feature("A")["geometry"])))]
    forest_atlas.load(layer, gdal)
    forest_atlas.load(layer, [({"NOM_AP": "B"}, gdal[0][1])])
    names = set(ReferenceLayer.objects.values_list("name", flat=True))
    assert names == {"B", other.name}


def test_command_reads_a_local_export(tmp_path):
    path = tmp_path / "aires.geojson"
    data = {"type": "FeatureCollection", "features": [feature("Bénoué", x=13.5)]}
    path.write_text(json.dumps(data), encoding="utf-8")
    call_command("load_forest_atlas", "protected_areas", file=str(path))
    layer = ReferenceLayer.objects.get()
    assert layer.name == "Bénoué (Parc national)" and layer.geometry.srid == 4326
